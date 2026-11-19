"""Collect response-level Codex token metadata for explicitly registered threads."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

try:
    from event_store import EventStoreError, _read_event, append_event
    from user_rules import UserRulesError, atomic_private_write, private_directory, private_lock
except ModuleNotFoundError:
    from scripts.event_store import EventStoreError, _read_event, append_event
    from scripts.user_rules import UserRulesError, atomic_private_write, private_directory, private_lock


class TokenUsageError(RuntimeError):
    """Raised when private token-usage data cannot be read or safely recorded."""


SCHEMA_VERSION = 1
COUNTER_FIELDS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "output_tokens", "reasoning_output_tokens", "total_tokens",
)
THREAD_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
RESPONSE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
GOAL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_ROLLOUT_LINE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_FILES = 512
STALE_AFTER_SECONDS = 900
TYPE_PREFIX_PATTERN = re.compile(rb'^\s*\{\s*"timestamp"\s*:\s*"[^"\\]*(?:\\.[^"\\]*)*"\s*,\s*"type"\s*:\s*"([A-Za-z0-9_.-]{1,64})"')


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _opaque_id(prefix: str, value: str) -> str:
    return f"{prefix}-{_digest(value)[:24]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_timestamp(value) -> str:
    if not isinstance(value, str) or len(value) > 80:
        raise TokenUsageError("A Codex usage timestamp is missing or invalid.")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TokenUsageError("A Codex usage timestamp is invalid.") from error
    if instant.tzinfo is None:
        raise TokenUsageError("A Codex usage timestamp must include a timezone.")
    return instant.astimezone(timezone.utc).isoformat()


def _text(value, label: str, maximum: int = 256, required: bool = False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum or "\0" in value:
        raise TokenUsageError(f"The {label} is invalid.")
    return value


def _counter_value(value, field: str):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2**63 - 1:
        raise TokenUsageError(f"Codex reported an invalid {field} counter.")
    return value


def _normalize_usage(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise TokenUsageError("A Codex response usage record is malformed.")
    return {field: _counter_value(payload.get(field), field) for field in COUNTER_FIELDS}


def _event_type(line: bytes):
    match = TYPE_PREFIX_PATTERN.match(line[:4096])
    return match.group(1).decode("ascii") if match else None


def _iter_bounded_lines(stream):
    while True:
        start = stream.tell()
        line = stream.readline(MAX_ROLLOUT_LINE_BYTES + 1)
        if not line:
            return
        if line.endswith(b"\n"):
            yield start, stream.tell(), line
            continue
        if len(line) <= MAX_ROLLOUT_LINE_BYTES:
            return
        kind = _event_type(line[:4096])
        while line and not line.endswith(b"\n"):
            line = stream.readline(65536)
        yield start, stream.tell(), None if kind not in {"token_usage_record", "turn_context", "session_meta"} else b"\0oversize\0"


def _model_name(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 128 or "\0" in value:
        raise TokenUsageError("The Codex turn model metadata is invalid.")
    return value.strip()


def _metadata_source(payload: dict) -> dict:
    model_provider = _text(payload.get("model_provider"), "Codex model provider", 128)
    source = payload.get("source")
    if not isinstance(source, dict):
        source = payload.get("session_source")
    if not isinstance(source, dict):
        return {"kind": "root", "parent_thread_id": None, "name": None, "model_provider": model_provider}
    subagent = source.get("subagent")
    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
    if not isinstance(spawn, dict):
        return {"kind": "root", "parent_thread_id": None, "name": None, "model_provider": model_provider}
    parent_id = spawn.get("parent_thread_id")
    if parent_id is not None and (not isinstance(parent_id, str) or not THREAD_PATTERN.fullmatch(parent_id)):
        raise TokenUsageError("The Codex parent thread identifier is invalid.")
    name = (spawn.get("agent_path") or spawn.get("agent_nickname") or spawn.get("agent_role"))
    if name is not None:
        name = _text(name, "Codex subagent name", 120)
        if name and ("\n" in name or "\r" in name):
            raise TokenUsageError("The Codex subagent name is invalid.")
    return {"kind": "subagent", "parent_thread_id": parent_id, "name": name, "model_provider": model_provider}


def _decode_rollout_line(raw_line: bytes):
    try:
        payload = json.loads(raw_line.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise TokenUsageError("A registered Codex rollout contains an unreadable record.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str) or not isinstance(payload.get("payload"), dict):
        raise TokenUsageError("A registered Codex rollout record has an unsupported envelope.")
    return payload


def read_rollout(path: str | os.PathLike, expected_thread_id: str) -> dict:
    """Read only whitelisted rollout metadata, discarding every conversation record."""
    if not isinstance(expected_thread_id, str) or not THREAD_PATTERN.fullmatch(expected_thread_id):
        raise TokenUsageError("The registered Codex thread identifier is invalid.")
    source_path = Path(path)
    if source_path.is_symlink() or (hasattr(source_path, "is_junction") and source_path.is_junction()):
        raise TokenUsageError("The registered Codex rollout path is unsafe.")
    if not source_path.is_file() or not source_path.name.endswith(f"-{expected_thread_id}.jsonl"):
        raise TokenUsageError("The registered Codex rollout does not match its thread identifier.")
    metadata = {"thread_id": expected_thread_id, "session_id": None, "cli_version": None,
                "parent_thread_id": None, "agent_name": None, "agent_kind": "unknown", "model_provider": None}
    turn_models = {}
    responses = []
    try:
        with source_path.open("rb") as stream:
            for line_number, (_start, _end, line) in enumerate(_iter_bounded_lines(stream), start=1):
                if line == b"\0oversize\0":
                    raise TokenUsageError("A Codex usage metadata record exceeds its supported size.")
                if line is None:
                    continue
                kind = _event_type(line)
                if kind not in {"token_usage_record", "turn_context", "session_meta"}:
                    continue
                record = _decode_rollout_line(line)
                if record["type"] != kind:
                    continue
                payload = record["payload"]
                if kind == "session_meta":
                    thread_id = payload.get("id", payload.get("thread_id"))
                    if thread_id != expected_thread_id:
                        raise TokenUsageError("Codex session metadata does not match the registered thread.")
                    metadata["session_id"] = _text(payload.get("session_id"), "Codex session identifier", 128)
                    metadata["cli_version"] = _text(payload.get("cli_version"), "Codex CLI version", 80)
                    metadata["model_provider"] = _text(payload.get("model_provider"), "Codex model provider", 128)
                    metadata.update(_metadata_source(payload))
                    continue
                if kind == "turn_context":
                    turn_id = payload.get("turn_id")
                    model = _model_name(payload.get("model"))
                    if isinstance(turn_id, str) and turn_id and model:
                        turn_models[turn_id] = model
                    continue
                thread_id = payload.get("thread_id")
                response_id = payload.get("response_id")
                turn_id = _text(payload.get("turn_id"), "Codex turn identifier", 256, required=True)
                if thread_id != expected_thread_id:
                    raise TokenUsageError("Codex usage data does not match the registered thread.")
                if not isinstance(response_id, str) or not RESPONSE_PATTERN.fullmatch(response_id):
                    raise TokenUsageError("Codex usage data is missing a stable response identifier.")
                timestamp = _validate_timestamp(record.get("timestamp"))
                session_id = _text(payload.get("session_id"), "Codex session identifier", 128)
                root_turn_id = _text(payload.get("root_turn_id"), "Codex root turn identifier", 256)
                responses.append({
                    "thread_id": expected_thread_id,
                    "turn_id": turn_id,
                    "root_turn_id": root_turn_id,
                    "session_id": session_id,
                    "response_id": response_id,
                    "recorded_at": timestamp,
                    "model_name": turn_models.get(turn_id),
                    "usage": _normalize_usage(payload.get("usage")),
                    "source_line": line_number,
                })
    except OSError as error:
        raise TokenUsageError("The registered Codex rollout could not be read.") from error
    return {"metadata": metadata, "responses": responses, "format": "codex_rollout_jsonl_v1"}


def _windows_path(value: str) -> Path:
    if os.name == "nt":
        return Path(value).expanduser()
    windows_path = PureWindowsPath(value)
    if windows_path.drive and len(windows_path.drive) == 2 and windows_path.drive[1] == ":":
        drive = windows_path.drive[0].lower()
        return Path("/mnt") / drive / Path(*windows_path.parts[1:])
    return Path(value).expanduser()


def _codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        candidate = _windows_path(configured)
    elif os.environ.get("USERPROFILE"):
        candidate = _windows_path(os.environ["USERPROFILE"]) / ".codex"
    else:
        candidate = Path.home() / ".codex"
    try:
        original = Path(os.path.abspath(candidate))
        current = original
        while current != current.parent:
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise TokenUsageError("CODEX_HOME cannot contain a symbolic link.")
            current = current.parent
        resolved = candidate.resolve(strict=True)
        current = resolved
        while current != current.parent:
            if (current / ".git").exists():
                raise TokenUsageError("CODEX_HOME must be outside every Git working tree.")
            current = current.parent
        return resolved
    except (OSError, RuntimeError) as error:
        raise TokenUsageError("The Codex home directory is unavailable.") from error


def _validated_source_root(value) -> Path:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise TokenUsageError("An explicit Codex sessions directory is required.")
    candidate = _windows_path(value)
    try:
        root = candidate.resolve(strict=True)
        expected = (_codex_home() / "sessions").resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise TokenUsageError("The registered Codex sessions directory is unavailable.") from error
    if not root.is_dir() or root != expected:
        raise TokenUsageError("The source directory must be the sessions folder under the configured Codex home.")
    current = candidate
    while current != current.parent:
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise TokenUsageError("The registered Codex sessions path contains a symbolic link.")
        current = current.parent
    return root


def _usage_root(binding: dict) -> Path:
    account_root = Path(binding.get("account_root", ""))
    if not account_root.is_absolute() or account_root.is_symlink():
        raise TokenUsageError("The verified account storage binding is invalid.")
    root = account_root / "runtime" / "token-usage"
    try:
        root.resolve(strict=False).relative_to(account_root.resolve(strict=True))
        private_directory(root)
    except (OSError, RuntimeError, ValueError, UserRulesError) as error:
        raise TokenUsageError("Private token-usage runtime storage is unsafe.") from error
    return root


def _claim_root(binding: dict) -> Path:
    account = binding.get("user")
    if not isinstance(account, dict) or account.get("provider") != "github":
        raise TokenUsageError("The verified account binding is missing.")
    host, account_id = account.get("host"), account.get("id")
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
        raise TokenUsageError("The verified GitHub host is invalid.")
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise TokenUsageError("The verified GitHub account ID is invalid.")
    root = _codex_home() / "gag-dev-team" / "users" / host.lower() / str(account_id) / "token-usage" / "response-claims"
    try:
        home = _codex_home()
        root.resolve(strict=False).relative_to(home)
        current = home
        for part in root.relative_to(home).parts:
            current = current / part
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise TokenUsageError("The account-wide token-usage claim path is unsafe.")
            if (current / ".git").exists():
                raise TokenUsageError("The account-wide token-usage registry cannot be created inside a Git repository.")
            current.mkdir(mode=0o700, exist_ok=True)
            if not current.is_dir():
                raise TokenUsageError("The account-wide token-usage claim path is unsafe.")
            if os.name != "nt":
                os.chmod(current, 0o700)
        private_directory(root)
        if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
            raise TokenUsageError("The account-wide token-usage claim path is unsafe.")
    except (OSError, RuntimeError, ValueError, UserRulesError) as error:
        raise TokenUsageError("The account-wide token-usage claim path is unsafe.") from error
    return root


def _atomic_json(path: Path, payload: dict) -> None:
    try:
        content = (json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")
        atomic_private_write(path, content)
    except UserRulesError as error:
        raise TokenUsageError("Private token-usage state could not be written safely.") from error


def _read_json(path: Path, default: dict) -> dict:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise TokenUsageError("Private token-usage state is unsafe.")
    if not path.exists():
        return default
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise TokenUsageError("Private token-usage state exceeds its size limit.")
        value = json.loads(path.read_text(encoding="utf-8"))
    except TokenUsageError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TokenUsageError("Private token-usage state is unreadable or corrupt.") from error
    if not isinstance(value, dict):
        raise TokenUsageError("Private token-usage state has an invalid envelope.")
    return value


def _project_events(binding: dict) -> list[dict]:
    try:
        try:
            from environment_projection import _load_events
        except ModuleNotFoundError:
            from scripts.environment_projection import _load_events
        return _load_events(binding, {})
    except EventStoreError as error:
        raise TokenUsageError(str(error)) from error


def _source_id(binding: dict, thread_id: str) -> str:
    user = binding["user"]
    return _opaque_id("codex-source", f"{user['host']}:{user['id']}:{thread_id}")


def _agent_id(thread_id: str) -> str:
    return _opaque_id("agent", thread_id)


def _event(binding: dict, event_type: str, summary: str, data: dict, event_id: str | None = None,
           **references) -> dict:
    payload = {"event_type": event_type, "summary": summary, "data": data,
               "model": references.pop("model", {"source": "unknown"}), **references}
    try:
        return append_event(binding, payload, event_id)
    except EventStoreError as error:
        raise TokenUsageError(str(error)) from error


def record_collector_failure(binding: dict, collector_id: str) -> dict:
    """Record only a sanitized failure code; preserve the last successful sync time."""
    if not isinstance(collector_id, str) or not re.fullmatch(r"[a-f0-9]{32}", collector_id):
        raise TokenUsageError("The token collector identity is invalid.")
    state_root = _usage_root(binding)
    with private_lock(state_root / "state.lock"):
        state = _read_state(binding)
        event = _event(binding, "token.source.synced", "Token usage synchronization was incomplete.",
                       {"status": "partial", "failure_code": "collector_sync_failed",
                        "source_count": len(state["sources"]), "files_read": 0,
                        "records_seen": 0, "observations_added": 0, "duplicates": 0,
                        "failed_sources": 1},
                       f"token-collector-failure-{collector_id}")
        state["last_sync_status"] = "partial"
        _write_state(binding, state)
        return event


def _validate_goal_id(value) -> str:
    if not isinstance(value, str) or not GOAL_PATTERN.fullmatch(value):
        raise TokenUsageError("The goal identifier is invalid.")
    return value


def _read_state(binding: dict, events: list[dict] | None = None) -> dict:
    root = _usage_root(binding)
    try:
        state = _read_json(root / "state.json", {"schema_version": SCHEMA_VERSION, "sources": {}, "checkpoints": {}, "turn_models": {}})
        if state.get("schema_version") != SCHEMA_VERSION or not all(
                isinstance(state.get(key), dict) for key in ("sources", "checkpoints", "turn_models")):
            raise TokenUsageError("Private token-usage state has an unsupported schema.")
    except TokenUsageError:
        # The immutable registration history is authoritative; a damaged cache
        # loses only offsets and causes a safe source rescan on the next sync.
        state = {"schema_version": SCHEMA_VERSION, "sources": {}, "checkpoints": {}, "turn_models": {}}
    authoritative_events = events if events is not None else _project_events(binding)
    for event in authoritative_events:
        if event.get("event_type") != "token.source.registered":
            continue
        data = event.get("data", {})
        source_id = data.get("source_id")
        if isinstance(source_id, str) and isinstance(data.get("thread_id"), str):
            descriptor = state["sources"].setdefault(source_id, {**data, "registered_at": event.get("recorded_at"), "goal_ids": []})
            if isinstance(data.get("goal_id"), str) and data["goal_id"] not in descriptor["goal_ids"]:
                descriptor["goal_ids"].append(data["goal_id"])
            state["checkpoints"].setdefault(source_id, {})
            state["turn_models"].setdefault(source_id, {})
    return state


def _write_state(binding: dict, state: dict) -> None:
    _atomic_json(_usage_root(binding) / "state.json", state)


def _read_claim(path: Path) -> dict | None:
    claim = _read_json(path, {})
    if not claim:
        return None
    if (claim.get("schema_version") != SCHEMA_VERSION or not isinstance(claim.get("project_id"), str)
            or not isinstance(claim.get("event_id"), str)):
        raise TokenUsageError("An account-wide token-usage claim is corrupt.")
    return claim


def _claim_response(binding: dict, source_key: str, event_id: str) -> dict:
    root = _claim_root(binding)
    claim_path = root / f"{source_key}.json"
    project_id = binding.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise TokenUsageError("The verified project binding is invalid.")
    with private_lock(root / "claims.lock"):
        current = _read_claim(claim_path)
        if current is not None:
            return current
        return _publish_claim(claim_path, {"schema_version": SCHEMA_VERSION,
                                           "project_id": project_id, "event_id": event_id})


def _publish_claim(path: Path, claim: dict) -> dict:
    """Create a write-once cross-project receipt before its project event."""
    import tempfile

    descriptor, temporary_name = tempfile.mkstemp(prefix=".claim-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        content = json.dumps(claim, ensure_ascii=True, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            return claim
        except FileExistsError:
            existing = _read_claim(path)
            if existing is None:
                raise TokenUsageError("An account-wide token-usage claim is unreadable.")
            return existing
        except OSError as error:
            raise TokenUsageError("The account-wide token-usage claim could not be published safely.") from error
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def start_goal(binding: dict, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise TokenUsageError("Goal start requires a JSON object.")
    name = _text(payload.get("name"), "goal name", 200, required=True)
    thread_id = _text(payload.get("thread_id"), "Codex thread identifier", 128, required=True)
    if not THREAD_PATTERN.fullmatch(thread_id):
        raise TokenUsageError("The Codex thread identifier is invalid.")
    source_root = _validated_source_root(payload.get("source_root"))
    goal_id = payload.get("goal_id") or str(uuid.uuid4())
    goal_id = _validate_goal_id(goal_id)
    result = _event(binding, "goal.started", "Started an explicit token-usage goal.",
                    {"goal_id": goal_id, "name": name, "root_agent_id": _agent_id(thread_id),
                     "source_id": _source_id(binding, thread_id)}, f"goal-start-{_digest(goal_id)[:32]}")
    source = register_source(binding, {"thread_id": thread_id, "source_root": str(source_root),
                                      "goal_id": goal_id,
                                      "agent_name": payload.get("agent_name") or "orchestrator"})
    return {"goal": {"id": goal_id, "name": name, "status": "active", "started_at": result["event"]["recorded_at"]},
            "link": source["link"], "source": source}


def end_goal(binding: dict, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise TokenUsageError("Goal end requires a JSON object.")
    goal_id = _validate_goal_id(payload.get("goal_id"))
    events = _project_events(binding)
    existing = next((event for event in events if event.get("event_type") == "goal.ended"
                     and event.get("data", {}).get("goal_id") == goal_id), None)
    if existing:
        return {"goal_id": goal_id, "ended_at": existing["recorded_at"], "created": False}
    if not any(event.get("event_type") == "goal.started" and event.get("data", {}).get("goal_id") == goal_id for event in events):
        raise TokenUsageError("The requested token-usage goal does not exist in this project.")
    ended = _event(binding, "goal.ended", "Ended an explicit token-usage goal.", {"goal_id": goal_id},
                   f"goal-end-{_digest(goal_id)[:32]}")
    return {"goal_id": goal_id, "ended_at": ended["event"]["recorded_at"], "created": ended["created"]}


def register_source(binding: dict, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise TokenUsageError("Source registration requires a JSON object.")
    thread_id = _text(payload.get("thread_id"), "Codex thread identifier", 128, required=True)
    if not THREAD_PATTERN.fullmatch(thread_id):
        raise TokenUsageError("The Codex thread identifier is invalid.")
    source_root = _validated_source_root(payload.get("source_root"))
    goal_id = payload.get("goal_id")
    if goal_id is not None:
        goal_id = _validate_goal_id(goal_id)
    parent_thread_id = _text(payload.get("parent_thread_id"), "parent thread identifier", 128)
    if parent_thread_id is not None and not THREAD_PATTERN.fullmatch(parent_thread_id):
        raise TokenUsageError("The parent thread identifier is invalid.")
    agent_name = _text(payload.get("agent_name"), "agent name", 120) or ("orchestrator" if not parent_thread_id else "subagent")
    source_id = _source_id(binding, thread_id)
    agent_id = _agent_id(thread_id)
    state_root = _usage_root(binding)
    with private_lock(state_root / "state.lock"):
        state = _read_state(binding)
        previous = state["sources"].get(source_id)
        inherited_parent = (previous.get("parent_thread_id") if isinstance(previous, dict)
                           and previous.get("ancestry_verified") and parent_thread_id is None else None)
        selected_parent = parent_thread_id or inherited_parent
        inherited_metadata = ({key: previous[key] for key in ("kind", "name", "model_provider") if key in previous}
                              if isinstance(previous, dict) else {})
        descriptor = {"source_id": source_id, "provider": "codex", "format": "rollout_jsonl",
                      "thread_id": thread_id, "source_root": str(source_root), "parent_thread_id": selected_parent,
                      "agent_id": agent_id, "agent_name": agent_name, "goal_id": goal_id,
                      "registered_at": previous.get("registered_at") if isinstance(previous, dict) else _now(),
                      "ancestry_verified": bool(isinstance(previous, dict) and previous.get("ancestry_verified")
                                                 and previous.get("parent_thread_id") == selected_parent),
                      **inherited_metadata}
        path_digest = _digest(str(source_root))[:12]
        descriptor_digest = _digest(source_id + path_digest + (goal_id or "unassigned")
                                    + (parent_thread_id or "") + agent_name)
        event_id = f"token-source-{descriptor_digest[:32]}"
        _event(binding, "token.source.registered", "Registered an explicit Codex token-usage source.",
               {"source_id": source_id, "provider": "codex", "format": "rollout_jsonl", "thread_id": thread_id,
                 "source_root": str(source_root), "parent_thread_id": parent_thread_id,
                "agent_id": agent_id, "agent_name": agent_name, "goal_id": goal_id}, event_id,
               agent_id=agent_id, session_id=thread_id)
        previous_goals = list(previous.get("goal_ids", [])) if isinstance(previous, dict) else []
        if previous and isinstance(previous.get("goal_id"), str):
            previous_goals.append(previous["goal_id"])
        if goal_id:
            previous_goals.append(goal_id)
        descriptor["goal_ids"] = sorted(set(previous_goals))
        state["sources"][source_id] = descriptor
        state["checkpoints"].setdefault(source_id, {})
        state["turn_models"].setdefault(source_id, {})
        _write_state(binding, state)
    link = None
    if goal_id is not None:
        link = link_agent(binding, {"goal_id": goal_id, "thread_id": thread_id,
                                    "parent_thread_id": parent_thread_id, "source_root": str(source_root),
                                    "agent_name": agent_name, "_source_registered": True})
    return {"source_id": source_id, "thread_id": thread_id, "agent_id": agent_id,
            "goal_id": goal_id, "registered_at": descriptor["registered_at"], "link": link,
            "changed": previous != descriptor}


def link_agent(binding: dict, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise TokenUsageError("Agent linking requires a JSON object.")
    goal_id = _validate_goal_id(payload.get("goal_id"))
    thread_id = _text(payload.get("thread_id"), "Codex thread identifier", 128, required=True)
    if not THREAD_PATTERN.fullmatch(thread_id):
        raise TokenUsageError("The Codex thread identifier is invalid.")
    parent_thread_id = _text(payload.get("parent_thread_id"), "parent thread identifier", 128)
    agent_name = _text(payload.get("agent_name"), "agent name", 120)
    events = _project_events(binding)
    if not any(event.get("event_type") == "goal.started" and event.get("data", {}).get("goal_id") == goal_id
               for event in events):
        raise TokenUsageError("The requested token-usage goal does not exist in this project.")
    if not payload.get("_source_registered"):
        registered = register_source(binding, {"thread_id": thread_id, "source_root": payload.get("source_root"),
                                               "goal_id": None, "parent_thread_id": parent_thread_id,
                                               "agent_name": agent_name})
        agent_id = registered["agent_id"]
    else:
        agent_id = _agent_id(thread_id)
    for event in reversed(events):
        if event.get("event_type") == "goal.agent.linked" and event.get("data", {}).get("thread_id") == thread_id:
            if event.get("data", {}).get("goal_id") == goal_id and not _agent_link_closed_after(
                    events, thread_id, event["recorded_at"], goal_id):
                return {"goal_id": goal_id, "agent_id": agent_id, "linked_at": event["recorded_at"], "created": False}
            if event.get("recorded_at") and not _agent_link_closed_after(
                    events, thread_id, event["recorded_at"], event.get("data", {}).get("goal_id")):
                _event(binding, "goal.agent.unlinked", "Closed an explicit agent-to-goal usage binding.",
                       {"goal_id": event.get("data", {}).get("goal_id"), "thread_id": thread_id,
                        "agent_id": agent_id, "reason": "relinked"})
                break
    linked = _event(binding, "goal.agent.linked", "Linked a Codex agent to an explicit token-usage goal.",
                    {"goal_id": goal_id, "thread_id": thread_id, "agent_id": agent_id,
                     "parent_thread_id": parent_thread_id, "agent_name": agent_name})
    return {"goal_id": goal_id, "agent_id": agent_id, "linked_at": linked["event"]["recorded_at"], "created": linked["created"]}


def _agent_link_closed_after(events: list[dict], thread_id: str, linked_at: str, goal_id: str | None) -> bool:
    return any(event.get("event_type") in {"goal.agent.unlinked", "goal.ended"}
               and event.get("recorded_at", "") >= linked_at
               and ((event.get("event_type") == "goal.ended" and event.get("data", {}).get("goal_id") == goal_id)
                    or (event.get("event_type") == "goal.agent.unlinked"
                        and event.get("data", {}).get("thread_id") == thread_id
                        and event.get("data", {}).get("goal_id") == goal_id))
               for event in events)


def correct_attribution(binding: dict, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise TokenUsageError("Attribution correction requires a JSON object.")
    thread_id = _text(payload.get("thread_id"), "Codex thread identifier", 128, required=True)
    response_id = _text(payload.get("response_id"), "Codex response identifier", 256, required=True)
    if not THREAD_PATTERN.fullmatch(thread_id) or not RESPONSE_PATTERN.fullmatch(response_id):
        raise TokenUsageError("The source response identity is invalid.")
    goal_id = payload.get("goal_id")
    if goal_id is not None:
        goal_id = _validate_goal_id(goal_id)
    reason = _text(payload.get("reason"), "attribution correction reason", 1000, required=True)
    events = _project_events(binding)
    target = next((event for event in events if event.get("event_type") == "token.usage.observed"
                   and event.get("data", {}).get("thread_id") == thread_id
                   and event.get("data", {}).get("response_id") == response_id), None)
    if target is None:
        raise TokenUsageError("The requested Codex response is not present in this project history.")
    if goal_id is not None and not any(event.get("event_type") == "goal.started"
                                       and event.get("data", {}).get("goal_id") == goal_id for event in events):
        raise TokenUsageError("The target token-usage goal does not exist in this project.")
    agent_thread_id = payload.get("agent_thread_id") or thread_id
    if agent_thread_id is not None and not THREAD_PATTERN.fullmatch(agent_thread_id):
        raise TokenUsageError("The target Codex agent identity is invalid.")
    correction_id = f"usage-correction-{_digest(target['event_id'] + str(goal_id) + str(agent_thread_id) + reason)[:32]}"
    correction = _event(binding, "token.usage.attribution.corrected", "Corrected attribution of a Codex response.",
                        {"target_event_id": target["event_id"], "thread_id": thread_id, "response_id": response_id,
                         "goal_id": goal_id, "agent_thread_id": agent_thread_id,
                         "agent_id": _agent_id(agent_thread_id), "reason": reason}, correction_id,
                        causes=[target["event_id"]])
    return {"created": correction["created"], "event_id": correction["event"]["event_id"],
            "attribution_status": "corrected"}


def _source_files(source_root: Path, thread_id: str) -> list[Path]:
    files = []
    suffix = f"-{thread_id}.jsonl"
    for path in source_root.rglob("*.jsonl"):
        if path.name.endswith(suffix):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise TokenUsageError("A registered Codex rollout is a symbolic link.")
            if path.is_file():
                files.append(path)
                if len(files) > MAX_SOURCE_FILES:
                    raise TokenUsageError("The registered Codex thread has too many rollout files.")
    return sorted(files, key=lambda path: path.as_posix())


def _stable_response_key(binding: dict, thread_id: str, response_id: str) -> str:
    user = binding["user"]
    return _digest(f"{user['host']}:{user['id']}:codex:{thread_id}:{response_id}")


def _event_usage_payload(binding: dict, source: dict, response: dict, metadata: dict) -> tuple[dict, str]:
    source_key = _stable_response_key(binding, response["thread_id"], response["response_id"])
    model_name = response.get("model_name")
    model_provider = metadata.get("model_provider")
    model = {"provider": model_provider, "requested": model_name,
             "observed": None, "source": "declared" if model_name else "unknown"}
    event_data = {
        "source_id": source["source_id"], "source_provider": "codex", "source_format": "rollout_jsonl",
        "thread_id": response["thread_id"], "session_id": response.get("session_id"),
        "turn_id": response["turn_id"], "root_turn_id": response.get("root_turn_id"),
        "response_id": response["response_id"], "source_key_digest": source_key,
        "agent_id": source["agent_id"], "agent_name": source.get("agent_name"),
        "parent_thread_id": metadata.get("parent_thread_id") or source.get("parent_thread_id"),
        "model": {"name": model_name, "provider": model_provider,
                  "source": "turn_context" if model_name else "unknown",
                  "verification": "requested" if model_name else "unknown"},
        "usage": response["usage"],
    }
    event_id = f"usage-{source_key[:48]}"
    payload = {"event_type": "token.usage.observed", "recorded_at": response["recorded_at"],
               "session_id": response.get("session_id"), "agent_id": source["agent_id"],
               "task_id": response.get("root_turn_id"), "attempt_id": response["response_id"],
               "model": model, "category": "token_usage", "summary": "Recorded Codex response-level token usage.",
               "data": event_data}
    return payload, event_id


def sync_usage(binding: dict, payload: dict | None = None) -> dict:
    """Synchronize explicitly registered Codex threads; repeated response IDs are ignored."""
    payload = payload or {}
    if not isinstance(payload, dict):
        raise TokenUsageError("Usage synchronization requires a JSON object.")
    requested_source = payload.get("source_id")
    if requested_source is not None and (not isinstance(requested_source, str) or not requested_source.startswith("codex-source-")):
        raise TokenUsageError("The requested token-usage source identifier is invalid.")
    usage_root = _usage_root(binding)
    runtime_root = Path(binding["runtime_root"])
    try:
        with private_lock(Path(binding["account_root"]) / "runtime" / "token-usage.lock"):
            all_events = _project_events(binding)
            state = _read_state(binding, all_events)
            sources = [source for source in state["sources"].values()
                       if requested_source is None or source.get("source_id") == requested_source]
            if requested_source and not sources:
                raise TokenUsageError("The requested Codex source is not registered for this project.")
            active_links = _active_link_map(all_events)
            previously_partial = any(event.get("event_type") == "token.source.synced"
                                     and event.get("data", {}).get("status") == "partial"
                                     and event.get("data", {}).get("failure_code") != "collector_sync_failed"
                                     for event in all_events)
            added = duplicates = files_read = records_seen = failed = 0
            for source in sources:
                source_root = _validated_source_root(source.get("source_root"))
                ancestry_valid = (not source.get("parent_thread_id") or bool(source.get("ancestry_verified")))
                ancestry_checked = ancestry_valid
                files = _source_files(source_root, source["thread_id"])
                files_read += len(files)
                if not files:
                    failed += 1
                    continue
                checkpoints = state["checkpoints"].setdefault(source["source_id"], {})
                turn_models = state["turn_models"].setdefault(source["source_id"], {})
                for file_path in files:
                    path_key = _digest(str(file_path))[:32]
                    stat = file_path.stat()
                    file_id = f"{stat.st_dev}:{stat.st_ino}"
                    checkpoint = checkpoints.get(path_key, {})
                    offset = checkpoint.get("offset", 0)
                    if (checkpoint.get("file_id") != file_id or isinstance(offset, bool)
                            or not isinstance(offset, int) or offset < 0 or stat.st_size < offset):
                        offset = 0
                    if offset == 0 and source.get("parent_thread_id"):
                        ancestry_valid = False
                        ancestry_checked = False
                    last_complete_offset = offset
                    try:
                        with file_path.open("rb") as stream:
                            stream.seek(offset)
                            while True:
                                line_start = stream.tell()
                                line = stream.readline(MAX_ROLLOUT_LINE_BYTES + 1)
                                if not line:
                                    break
                                if not line.endswith(b"\n"):
                                    if len(line) <= MAX_ROLLOUT_LINE_BYTES:
                                        break
                                    event_kind = _event_type(line[:4096])
                                    while line and not line.endswith(b"\n"):
                                        line = stream.readline(65536)
                                    last_complete_offset = stream.tell()
                                    if event_kind in {"token_usage_record", "turn_context", "session_meta"}:
                                        failed += 1
                                    continue
                                last_complete_offset = stream.tell()
                                if len(line) > MAX_ROLLOUT_LINE_BYTES:
                                    if _event_type(line[:4096]) in {"token_usage_record", "turn_context", "session_meta"}:
                                        failed += 1
                                    continue
                                kind = _event_type(line)
                                if kind is None and line.lstrip().startswith(b"{"):
                                    # Malformed or unsupported JSON envelopes degrade coverage,
                                    # but their contents are never parsed or copied.
                                    failed += 1
                                    continue
                                if kind not in {"token_usage_record", "turn_context", "session_meta"}:
                                    continue
                                try:
                                    record = _decode_rollout_line(line)
                                except TokenUsageError:
                                    failed += 1
                                    continue
                                source_payload = record["payload"]
                                if kind == "session_meta":
                                    if source_payload.get("id", source_payload.get("thread_id")) != source["thread_id"]:
                                        failed += 1
                                        continue
                                    metadata = _metadata_source(source_payload)
                                    ancestry_checked = True
                                    claimed_parent = source.get("parent_thread_id")
                                    ancestry_valid = (not claimed_parent or claimed_parent == metadata.get("parent_thread_id"))
                                    if not ancestry_valid:
                                        failed += 1
                                        continue
                                    source["ancestry_verified"] = True
                                    ancestry_checked = True
                                    if metadata.get("parent_thread_id") and not claimed_parent:
                                        source["parent_thread_id"] = metadata["parent_thread_id"]
                                    if metadata.get("name") and source.get("agent_name") in {None, "subagent"}:
                                        source["agent_name"] = metadata["name"]
                                    state["sources"][source["source_id"]].update(metadata)
                                    continue
                                if kind == "turn_context":
                                    turn_id = source_payload.get("turn_id")
                                    model_name = _model_name(source_payload.get("model"))
                                    if isinstance(turn_id, str) and turn_id and model_name:
                                        turn_models[turn_id] = model_name
                                    continue
                                thread_id = source_payload.get("thread_id")
                                response_id = source_payload.get("response_id")
                                if thread_id != source["thread_id"]:
                                    failed += 1
                                    continue
                                if not ancestry_valid:
                                    continue
                                if not isinstance(response_id, str) or not RESPONSE_PATTERN.fullmatch(response_id):
                                    failed += 1
                                    continue
                                records_seen += 1
                                try:
                                    response = {
                                        "thread_id": thread_id,
                                        "turn_id": _text(source_payload.get("turn_id"), "Codex turn identifier", 256, required=True),
                                        "root_turn_id": _text(source_payload.get("root_turn_id"), "Codex root turn identifier", 256),
                                        "session_id": _text(source_payload.get("session_id"), "Codex session identifier", 128),
                                        "response_id": response_id,
                                        "recorded_at": _validate_timestamp(record.get("timestamp")),
                                        "model_name": turn_models.get(source_payload.get("turn_id")),
                                        "usage": _normalize_usage(source_payload.get("usage")),
                                    }
                                except TokenUsageError:
                                    failed += 1
                                    continue
                                source_key = _stable_response_key(binding, thread_id, response_id)
                                payload_event, event_id = _event_usage_payload(binding, source, response, state["sources"][source["source_id"]])
                                attributed_here = any(
                                    link.get("goal_id") and _contains_interval(link, response["recorded_at"])
                                    for link in active_links.get(thread_id, [])
                                )
                                if not attributed_here and not (source.get("goal_id") or source.get("goal_ids")
                                                                or active_links.get(thread_id)):
                                    # A source registered without an explicit goal cannot claim
                                    # an unassigned response from another project.
                                    continue
                                claim = _claim_response(binding, source_key, event_id)
                                if claim.get("project_id") != binding["project_id"]:
                                    duplicates += 1
                                    continue
                                _event(binding, "token.usage.observed", payload_event["summary"], payload_event["data"], event_id,
                                       recorded_at=payload_event["recorded_at"], session_id=payload_event["session_id"],
                                       agent_id=payload_event["agent_id"], task_id=payload_event["task_id"],
                                       attempt_id=payload_event["attempt_id"], model=payload_event["model"], category="token_usage")
                                added += 1
                        checkpoints[path_key] = {"file_id": file_id, "offset": last_complete_offset,
                                                 "size": stat.st_size}
                    except OSError as error:
                        failed += 1
                        continue
                if source.get("parent_thread_id") and not ancestry_checked:
                    failed += 1
            synced_at = _now()
            if sources:
                state["last_synced_at"] = synced_at
                state["last_sync_status"] = "partial" if failed or previously_partial else "available"
                _write_state(binding, state)
            status = "unavailable" if not sources else ("partial" if failed or previously_partial else "available")
            latest_sync = next((event for event in reversed(all_events)
                                if event.get("event_type") == "token.source.synced"), None)
            should_record_sync = (latest_sync is None or latest_sync.get("data", {}).get("status") != status
                                  or records_seen > 0 or added > 0 or duplicates > 0 or failed > 0)
            if should_record_sync:
                sync_event = _event(binding, "token.source.synced", "Synchronized explicitly registered Codex token sources.",
                                    {"status": status, "source_count": len(sources), "files_read": files_read,
                                     "records_seen": records_seen, "observations_added": added,
                                     "duplicates": duplicates, "failed_sources": failed},
                                    f"token-sync-{uuid.uuid4().hex}")
                synced_at = sync_event["event"]["recorded_at"]
                if sources:
                    state["last_synced_at"] = synced_at
                    state["last_sync_status"] = status
                    _write_state(binding, state)
            return {"status": status, "last_synced_at": synced_at,
                    "files_read": files_read, "records_seen": records_seen,
                    "observations_added": added, "duplicates": duplicates,
                    "failed_sources": failed, "unassigned": None}
    except UserRulesError as error:
        raise TokenUsageError(str(error)) from error


def _active_link_map(events: list[dict]) -> dict:
    links = {}
    for event in events:
        data = event.get("data", {})
        thread_id = data.get("thread_id")
        if event.get("event_type") == "goal.agent.linked" and isinstance(thread_id, str):
            links.setdefault(thread_id, []).append({"goal_id": data.get("goal_id"), "agent_id": data.get("agent_id"),
                                                    "parent_thread_id": data.get("parent_thread_id"),
                                                    "agent_name": data.get("agent_name"),
                                                    "started_at": event.get("recorded_at"), "ended_at": None})
        elif event.get("event_type") == "goal.agent.unlinked" and isinstance(thread_id, str):
            for link in reversed(links.get(thread_id, [])):
                if link["ended_at"] is None:
                    link["ended_at"] = event.get("recorded_at")
                    break
        elif event.get("event_type") == "goal.ended":
            goal_id = data.get("goal_id")
            for thread_links in links.values():
                for link in thread_links:
                    if link["goal_id"] == goal_id and link["ended_at"] is None:
                        link["ended_at"] = event.get("recorded_at")
    return links


def _contains_interval(link: dict, recorded_at: str) -> bool:
    return link.get("started_at", "") <= recorded_at and (link.get("ended_at") is None or recorded_at < link["ended_at"])


def _unknown_usage(response_count=None) -> dict:
    return {"response_count": response_count, **{field: None for field in COUNTER_FIELDS}}


def _aggregate(rows: list[dict], known: bool) -> dict:
    if not known:
        return _unknown_usage(None)
    if not rows:
        return _unknown_usage(0)
    result = {"response_count": len(rows)}
    for field in COUNTER_FIELDS:
        values = [row.get("usage", {}).get(field) for row in rows]
        result[field] = sum(values) if all(isinstance(value, int) and not isinstance(value, bool) for value in values) else None
    return result


def usage_snapshot(binding: dict, filters: dict | None = None, events: list[dict] | None = None) -> dict:
    """Project immutable token events; this read path never synchronizes source files."""
    filters = filters or {}
    allowed_filters = {"period", "from", "to", "goal_id", "agent_id", "model"}
    if not isinstance(filters, dict) or set(filters) - allowed_filters:
        raise TokenUsageError("The token-usage filter set is invalid.")
    for field in ("from", "to", "goal_id", "agent_id", "model", "period"):
        value = filters.get(field)
        if value is not None and not isinstance(value, str):
            raise TokenUsageError(f"The token-usage {field} filter must be text.")
    if events is None:
        events = _project_events(binding)
    state = _read_state(binding, events)
    goals = {}
    source_events = []
    sync_events = []
    raw_usage = []
    corrections = {}
    for event in events:
        event_type = event.get("event_type")
        data = event.get("data", {})
        if event_type == "goal.started":
            goal_id = data.get("goal_id")
            if isinstance(goal_id, str):
                goals[goal_id] = {"id": goal_id, "name": data.get("name"), "status": "active",
                                  "started_at": event.get("recorded_at"), "ended_at": None,
                                  "root_agent_id": data.get("root_agent_id")}
        elif event_type == "goal.ended":
            goal = goals.get(data.get("goal_id"))
            if goal:
                goal["status"] = "ended"
                goal["ended_at"] = event.get("recorded_at")
        elif event_type == "token.source.registered":
            source_events.append(event)
        elif event_type == "token.source.synced":
            sync_events.append(event)
        elif event_type == "token.usage.observed":
            raw_usage.append(event)
        elif event_type == "token.usage.attribution.corrected":
            corrections[data.get("target_event_id")] = event
    links = _active_link_map(events)
    response_rows = []
    for event in raw_usage:
        data = event["data"]
        thread_id = data.get("thread_id")
        assigned = next((link for link in reversed(links.get(thread_id, [])) if _contains_interval(link, event["recorded_at"])), None)
        correction = corrections.get(event["event_id"])
        if correction:
            correction_data = correction["data"]
            goal_id = correction_data.get("goal_id")
            assigned_agent_id = correction_data.get("agent_id")
            attribution_status = "corrected"
        else:
            goal_id = assigned.get("goal_id") if assigned else None
            assigned_agent_id = data.get("agent_id")
            attribution_status = "assigned" if assigned else "unassigned"
        model = data.get("model") or {"name": None, "provider": None, "source": "unknown", "verification": "unknown"}
        row = {"id": _opaque_id("usage", event["event_id"]), "recorded_at": event["recorded_at"],
               "goal_id": goal_id, "agent_id": assigned_agent_id,
               "agent_name": assigned.get("agent_name") if assigned else data.get("agent_name"),
               "parent_agent_id": _agent_id((assigned.get("parent_thread_id") if assigned else data.get("parent_thread_id")))
               if (assigned and assigned.get("parent_thread_id")) or data.get("parent_thread_id") else None,
               "thread_id": thread_id, "model": model, "usage": data.get("usage", {}),
               "attribution_status": attribution_status}
        if not _matches_usage_filters(row, filters):
            continue
        response_rows.append(row)
    response_rows.sort(key=lambda item: (item["recorded_at"], item["id"]))
    root_agents_by_goal = {goal_id: {goal.get("root_agent_id")} for goal_id, goal in goals.items()}
    for event in events:
        if event.get("event_type") != "goal.agent.linked":
            continue
        data = event.get("data", {})
        if data.get("goal_id") in root_agents_by_goal and not data.get("parent_thread_id"):
            root_agents_by_goal[data["goal_id"]].add(data.get("agent_id"))
    root_agents = {agent_id for identifiers in root_agents_by_goal.values() for agent_id in identifiers if agent_id}
    latest_sync_status = (sync_events[-1].get("data", {}).get("status") if sync_events else state.get("last_sync_status"))
    known = bool(source_events) and latest_sync_status in {"available", "partial"}
    agents = {}
    for event in events:
        if event.get("event_type") == "goal.agent.linked":
            data = event.get("data", {})
            thread_id = data.get("thread_id")
            goal_id = data.get("goal_id")
            if isinstance(thread_id, str) and (filters.get("goal_id") is None or goal_id == filters["goal_id"]):
                agent_id = data.get("agent_id") or _agent_id(thread_id)
                agents[(agent_id, goal_id)] = {
                    "id": agent_id, "name": data.get("agent_name") or "Codex agent",
                    "parent_agent_id": _agent_id(data["parent_thread_id"]) if data.get("parent_thread_id") else None,
                    "thread_id": thread_id, "goal_id": goal_id,
                }
    for row in response_rows:
        agent_id = row.get("agent_id")
        if row.get("goal_id") is None and agent_id:
            agents.setdefault((agent_id, None), {
                "id": agent_id, "name": row.get("agent_name") or "Codex agent",
                "parent_agent_id": row.get("parent_agent_id"),
                "thread_id": row.get("thread_id"), "goal_id": None,
            })
    agent_filter = filters.get("agent_id")
    visible_by_goal = None
    if agent_filter:
        visible_by_goal = {}
        for selected in agents.values():
            if selected["id"] != agent_filter:
                continue
            descendants = {agent_filter}
            changed = True
            while changed:
                changed = False
                for candidate in agents.values():
                    if (candidate["goal_id"] == selected["goal_id"]
                            and candidate["parent_agent_id"] in descendants
                            and candidate["id"] not in descendants):
                        descendants.add(candidate["id"])
                        changed = True
            visible_by_goal[selected["goal_id"]] = descendants
        filtered_rows = [row for row in response_rows
                         if row.get("agent_id") in visible_by_goal.get(row.get("goal_id"), set())]
    else:
        filtered_rows = response_rows
    total_own = [row for row in filtered_rows
                 if row.get("agent_id") == agent_filter] if agent_filter else [
                     row for row in filtered_rows if row.get("agent_id") in root_agents]
    # The overall inclusive total covers every measured response in the same
    # filter scope, including observations that remain separately unassigned.
    total_inclusive = filtered_rows
    goal_rows = []
    for goal in goals.values():
        rows = [row for row in filtered_rows if row.get("goal_id") == goal["id"]]
        goal_rows.append({**goal,
                          "own": _aggregate([row for row in rows
                                             if row.get("agent_id") in root_agents_by_goal.get(goal["id"], set())], known),
                          "inclusive": _aggregate(rows, known)})
    agent_rows = []
    for agent in agents.values():
        descendants = {agent["id"]}
        changed = True
        while changed:
            changed = False
            for candidate in agents.values():
                if (candidate["goal_id"] == agent["goal_id"]
                        and candidate["parent_agent_id"] in descendants and candidate["id"] not in descendants):
                    descendants.add(candidate["id"])
                    changed = True
        if visible_by_goal is not None and agent["id"] not in visible_by_goal.get(agent["goal_id"], set()):
            continue
        rows = [row for row in filtered_rows if row.get("goal_id") == agent["goal_id"]
                and row.get("agent_id") in descendants]
        own_rows = [row for row in filtered_rows if row.get("goal_id") == agent["goal_id"]
                    and row.get("agent_id") == agent["id"]]
        agent_rows.append({key: value for key, value in agent.items() if key != "thread_id"} | {
            "own": _aggregate(own_rows, known), "inclusive": _aggregate(rows, known)})
    model_groups = {}
    for row in filtered_rows:
        model = row["model"]
        key = f"{model.get('provider')}:{model.get('name')}:{model.get('source')}"
        group = model_groups.setdefault(key, {"id": _opaque_id("model", key), "name": model.get("name"),
                                              "provider": model.get("provider"), "source": model.get("source"),
                                              "verification": model.get("verification"), "rows": []})
        group["rows"].append(row)
    model_rows = []
    for group in model_groups.values():
        model_rows.append({key: value for key, value in group.items() if key != "rows"} | {
            "own": _aggregate([row for row in group["rows"]
                               if row.get("agent_id") == agent_filter] if agent_filter else
                              [row for row in group["rows"] if row.get("agent_id") in root_agents], known),
            "inclusive": _aggregate(group["rows"], known)})
    unassigned_rows = [row for row in filtered_rows if row.get("goal_id") is None]
    last_sync = state.get("last_synced_at") or (sync_events[-1]["recorded_at"] if sync_events else None)
    status = "unavailable"
    if source_events:
        latest_sync = sync_events[-1] if sync_events else None
        sync_status = latest_sync.get("data", {}).get("status") if latest_sync else state.get("last_sync_status", "unavailable")
        if sync_status == "incompatible":
            status = "incompatible"
        elif not latest_sync or sync_status == "unavailable":
            status = "unavailable"
        elif sync_status == "partial":
            status = "partial"
        elif last_sync:
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_sync.replace("Z", "+00:00"))).total_seconds()
                status = "stale" if age > STALE_AFTER_SECONDS else "available"
            except ValueError:
                status = "partial"
    coverage = {"registered_sources": len(state["sources"]),
                "available_sources": len({event.get("data", {}).get("source_id") for event in source_events}),
                "synced_sources": (sync_events[-1].get("data", {}).get("source_count") if sync_events else None),
                "failed_sources": (sync_events[-1].get("data", {}).get("failed_sources") if sync_events else None),
                "responses_seen": len(filtered_rows) if known else None,
                "responses_attributed": sum(1 for row in filtered_rows if row.get("goal_id")) if known else None,
                "responses_unassigned": len(unassigned_rows) if known else None,
                "models_known": sum(1 for row in response_rows if row["model"].get("name")) if known else None}
    return {"source": {"provider": "codex", "format": "rollout_jsonl", "status": status},
            "status": status, "last_synced_at": last_sync, "coverage": coverage,
            "filters": {key: filters.get(key) for key in sorted(allowed_filters) if filters.get(key) is not None},
            "totals": {"own": _aggregate(total_own, known), "inclusive": _aggregate(total_inclusive, known)},
            "goals": sorted(goal_rows, key=lambda goal: (goal.get("started_at") or "", goal["id"]), reverse=True),
            "agents": sorted(agent_rows, key=lambda agent: agent["id"]),
            "models": sorted(model_rows, key=lambda model: model["id"]),
                 "responses": [{key: value for key, value in row.items() if key != "thread_id"} for row in filtered_rows],
            "unassigned": {"response_count": len(unassigned_rows) if known else None,
                           "usage": _aggregate(unassigned_rows, known)}}


def _matches_usage_filters(row: dict, filters: dict) -> bool:
    goal_id = filters.get("goal_id")
    if goal_id is not None and row.get("goal_id") != goal_id:
        return False
    model_filter = filters.get("model")
    if model_filter is not None and model_filter not in {row.get("model", {}).get("name"), row.get("model", {}).get("provider")}:
        return False
    for name in ("from", "to"):
        boundary = filters.get(name)
        if boundary:
            boundary_time = _validate_timestamp(boundary)
            if (row["recorded_at"] < boundary_time if name == "from" else row["recorded_at"] > boundary_time):
                return False
    period = filters.get("period")
    if period and period != "all":
        days = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}.get(period)
        if days is None:
            raise TokenUsageError("Token-usage period must be 1d, 7d, 30d, 90d, or all.")
        if datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00")) < datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=days):
            return False
    return True
