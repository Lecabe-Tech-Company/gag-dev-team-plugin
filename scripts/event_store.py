"""Append immutable account-scoped JSON events to private Git metadata."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


class EventStoreError(RuntimeError):
    """Raised when a private event cannot be validated or safely persisted."""


class EventConflictError(EventStoreError):
    """Raised when an event identifier is reused with different event content."""


EVENT_TYPES = {
    "identity.observed", "session.started", "session.ended", "attempt.recorded",
    "rule.versioned", "rule.deactivated", "skill.versioned", "skill.deactivated",
    "issue.opened", "issue.resolved", "issue.corrected",
    "goal.started", "goal.ended", "goal.agent.linked", "goal.agent.unlinked",
    "token.source.registered", "token.source.synced", "token.usage.observed", "token.usage.attribution.corrected",
    "extension.discovered", "extension.downloaded", "extension.reviewed",
    "extension.installed", "extension.activated", "extension.deactivated",
    "extension.failed", "extension.updated", "extension.removed", "legacy.imported",
}
MODEL_SOURCES = {"unknown", "configured", "declared", "observed"}
EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,39}$")
MAX_EVENT_BYTES = 256 * 1024
SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{24,}\b"),
)


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: dict) -> str:
    normalized = dict(value)
    if normalized.get("recorded_at_source") == "writer":
        normalized.pop("recorded_at", None)
    normalized.pop("payload_digest", None)
    if isinstance(normalized.get("user"), dict):
        normalized["user"] = {key: item for key, item in normalized["user"].items() if key != "login"}
    return hashlib.sha256(_canonical(normalized)).hexdigest()


def _legacy_digest(value: dict, *, include_login: bool = False) -> str:
    normalized = dict(value)
    normalized.pop("recorded_at", None)
    normalized.pop("recorded_at_source", None)
    normalized.pop("payload_digest", None)
    if not include_login and isinstance(normalized.get("user"), dict):
        normalized["user"] = {key: item for key, item in normalized["user"].items() if key != "login"}
    return hashlib.sha256(_canonical(normalized)).hexdigest()


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()) or (
            path.resolve(strict=False) != Path(os.path.abspath(path))
        )
    except OSError:
        return True


def _ensure_directory(path: Path, root: Path) -> None:
    try:
        relative = path.relative_to(root)
        current = root
    except ValueError as error:
        raise EventStoreError("The event directory is outside its private project root.") from error
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise EventStoreError("The event directory contains a symbolic link.")
        try:
            current.mkdir(mode=0o700, exist_ok=True)
        except OSError as error:
            raise EventStoreError("The event directory could not be created safely.") from error
        if _is_link(current) or not current.is_dir():
            raise EventStoreError("The event directory is unsafe.")
        if os.name != "nt":
            os.chmod(current, 0o700)


@contextlib.contextmanager
def _event_lock(binding: dict):
    runtime_root = Path(binding["runtime_root"])
    lock_path = runtime_root / "events.lock"
    if _is_link(lock_path):
        raise EventStoreError("The event lock path is unsafe.")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise EventStoreError("The private event store cannot be locked safely.") from error
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            import time
            deadline = time.monotonic() + 10
            while True:
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise EventStoreError("The private event store is busy; retry the operation.")
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
        if os.name != "nt":
            os.chmod(lock_path, 0o600)
        yield
    finally:
        if locked:
            if os.name == "nt":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _validate_binding(binding: dict) -> tuple[dict, Path, Path]:
    if not isinstance(binding, dict):
        raise EventStoreError("A verified project binding is required.")
    user = binding.get("user")
    if not isinstance(user, dict) or user.get("provider") != "github":
        raise EventStoreError("A verified GitHub account is required for event storage.")
    if isinstance(user.get("id"), bool) or not isinstance(user.get("id"), int) or user["id"] <= 0:
        raise EventStoreError("The project binding has an invalid GitHub account ID.")
    if not all(isinstance(binding.get(key), str) and binding[key] for key in ("project_id", "private_root", "events_root", "runtime_root")):
        raise EventStoreError("The project binding is incomplete.")
    raw_paths = [Path(binding[key]) for key in ("private_root", "events_root", "runtime_root")]
    if any(_is_link(path) for path in raw_paths):
        raise EventStoreError("The private event binding contains a symbolic link.")
    root = raw_paths[0].resolve(strict=True)
    events_root, runtime_root = raw_paths[1:]
    for path in (events_root, runtime_root):
        try:
            path.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as error:
            raise EventStoreError("The event store binding escapes its private project root.") from error
    return user, root, events_root


def _validate_payload(binding: dict, payload: dict, event_id: str | None) -> tuple[dict, str]:
    if not isinstance(payload, dict):
        raise EventStoreError("An event payload must be a JSON object.")
    event_type = payload.get("event_type")
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise EventStoreError("The event type is not supported by the current event schema.")
    identifier = event_id or payload.get("event_id") or str(uuid.uuid4())
    if not isinstance(identifier, str) or not EVENT_ID_PATTERN.fullmatch(identifier):
        raise EventStoreError("The event identifier is invalid.")
    model = payload.get("model", {})
    if not isinstance(model, dict):
        raise EventStoreError("The event model provenance is invalid.")
    source = model.get("source", "unknown")
    if not isinstance(source, str) or source not in MODEL_SOURCES:
        raise EventStoreError("The event model provenance is invalid.")
    for field in ("provider", "requested", "observed"):
        value = model.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > 256 or "\0" in value):
            raise EventStoreError("The event model identity is invalid.")
    if source == "observed" and not model.get("observed"):
        raise EventStoreError("An observed model must include the observed model name.")
    if source in {"configured", "declared"} and not model.get("requested"):
        raise EventStoreError("Configured or declared model provenance must include the model name.")
    causes = payload.get("causes", [])
    if not isinstance(causes, list) or any(not isinstance(item, str) or len(item) > 128 for item in causes):
        raise EventStoreError("Event causal references must be a list of short identifiers.")
    summary = payload.get("summary", "")
    data = payload.get("data", {})
    if not isinstance(summary, str) or len(summary) > 2000 or "\0" in summary:
        raise EventStoreError("The event summary is invalid or exceeds its size limit.")
    if "\n" in summary or "\r" in summary:
        raise EventStoreError("Event summaries must be concise single-line descriptions, not process output.")
    if not isinstance(data, dict):
        raise EventStoreError("Event data must be a JSON object.")
    operational_event = event_type.startswith(("session.", "attempt.", "issue.", "extension.", "goal.", "token."))

    def reject_sensitive_keys(value, depth=0):
        if depth > 16:
            raise EventStoreError("Event data exceeds the supported nesting depth.")
        if isinstance(value, dict):
            for key, nested in value.items():
                if not isinstance(key, str):
                    raise EventStoreError("Event data keys must be text.")
                normalized_key = key.lower().replace("-", "_")
                if operational_event and normalized_key in {
                    "prompt", "raw_prompt", "messages", "conversation", "transcript", "access_token",
                    "refresh_token", "token", "password", "authorization", "cookie", "credential_dump",
                    "stdout", "stderr", "terminal_output", "raw_output",
                }:
                    raise EventStoreError("Private prompts, credentials, and full process output cannot be recorded.")
                reject_sensitive_keys(nested, depth + 1)
        elif isinstance(value, list):
            for nested in value:
                reject_sensitive_keys(nested, depth + 1)
        elif isinstance(value, str) and operational_event and any(pattern.search(value) for pattern in SENSITIVE_PATTERNS):
            raise EventStoreError("A value matching a common credential format cannot be recorded.")

    reject_sensitive_keys({"summary": summary, "model": model, "data": data})
    try:
        safe_data = json.loads(_canonical(data).decode("utf-8"))
    except (TypeError, ValueError, UnicodeError) as error:
        raise EventStoreError("Event data must contain JSON-compatible values.") from error
    user, _root, _events_root = _validate_binding(binding)
    event = {
        "schema_version": 1,
        "event_id": identifier,
        "event_type": event_type,
        "recorded_at": payload.get("recorded_at"),
        "recorded_at_source": "provided" if payload.get("recorded_at") is not None else "writer",
        "project_id": binding["project_id"],
        "user": user,
        "session_id": payload.get("session_id"),
        "agent_id": payload.get("agent_id"),
        "task_id": payload.get("task_id"),
        "attempt_id": payload.get("attempt_id"),
        "issue_id": payload.get("issue_id"),
        "causes": causes,
        "model": {
            "provider": model.get("provider"),
            "requested": model.get("requested"),
            "observed": model.get("observed"),
            "source": model.get("source", "unknown"),
        },
        "category": payload.get("category"),
        "severity": payload.get("severity"),
        "attribution": payload.get("attribution"),
        "summary": summary,
        "data": safe_data,
    }
    if event["recorded_at"] is not None and not isinstance(event["recorded_at"], str):
        raise EventStoreError("The event timestamp must be ISO 8601 text.")
    for field in ("session_id", "agent_id", "task_id", "attempt_id", "issue_id", "category", "severity", "attribution"):
        value = event[field]
        if value is not None and (not isinstance(value, str) or len(value) > 256 or "\0" in value):
            raise EventStoreError(f"The event {field} value is invalid.")
    digest = _digest(event)
    return event, digest


def _read_event(path: Path) -> dict:
    if _is_link(path) or not path.is_file() or path.stat().st_size > MAX_EVENT_BYTES:
        raise EventStoreError("An event record is unsafe or exceeds its size limit.")
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EventStoreError("An immutable event record is unreadable or corrupt.") from error
    required = {
        "schema_version", "event_id", "event_type", "recorded_at", "recorded_at_source", "project_id", "user", "session_id",
        "agent_id", "task_id", "attempt_id", "issue_id", "causes", "model", "category", "severity",
        "attribution", "summary", "data", "payload_digest",
    }
    legacy_required = required - {"recorded_at_source"}
    if not isinstance(event, dict) or set(event) not in (required, legacy_required):
        raise EventStoreError("An immutable event record does not match the required envelope.")
    is_legacy = "recorded_at_source" not in event
    if (event.get("schema_version") != 1 or not isinstance(event.get("event_id"), str)
            or not EVENT_ID_PATTERN.fullmatch(event["event_id"])
            or not isinstance(event.get("event_type"), str) or event.get("event_type") not in EVENT_TYPES
            or (not is_legacy and (not isinstance(event.get("recorded_at_source"), str)
                                   or event.get("recorded_at_source") not in {"writer", "provided"}))
            or not isinstance(event.get("project_id"), str) or not event["project_id"]):
        raise EventStoreError("An immutable event record has invalid identity or version fields.")
    if path.name != f"{event['event_id']}.json":
        raise EventStoreError("An immutable event filename does not match its identifier.")
    user = event.get("user")
    if (not isinstance(user, dict) or set(user) != {"provider", "host", "id", "login"}
            or user.get("provider") != "github" or not isinstance(user.get("host"), str)
            or isinstance(user.get("id"), bool) or not isinstance(user.get("id"), int) or user["id"] <= 0
            or not isinstance(user.get("login"), str) or not LOGIN_PATTERN.fullmatch(user["login"])):
        raise EventStoreError("An immutable event record has invalid account fields.")
    if (not isinstance(event.get("model"), dict)
            or set(event["model"]) != {"provider", "requested", "observed", "source"}
            or not isinstance(event["model"].get("source"), str)
            or event["model"].get("source") not in MODEL_SOURCES):
        raise EventStoreError("An immutable event record has invalid model provenance.")
    if (not isinstance(event.get("causes"), list)
            or any(not isinstance(value, str) or len(value) > 128 for value in event["causes"])
            or not isinstance(event.get("data"), dict)):
        raise EventStoreError("An immutable event record has invalid causal or data fields.")
    for field in ("provider", "requested", "observed"):
        value = event["model"].get(field)
        if value is not None and (not isinstance(value, str) or len(value) > 256):
            raise EventStoreError("An immutable event record has invalid model fields.")
    for field in ("session_id", "agent_id", "task_id", "attempt_id", "issue_id", "category", "severity", "attribution"):
        value = event.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > 256):
            raise EventStoreError("An immutable event record has invalid reference fields.")
    if not isinstance(event.get("summary"), str) or len(event["summary"]) > 2000 or "\n" in event["summary"] or "\r" in event["summary"]:
        raise EventStoreError("An immutable event record has an invalid summary.")
    if not isinstance(event.get("payload_digest"), str) or not re.fullmatch(r"[a-f0-9]{64}", event["payload_digest"]):
        raise EventStoreError("An immutable event record has an invalid payload digest.")
    try:
        expected_digests = ({_legacy_digest(event), _legacy_digest(event, include_login=True)}
                            if is_legacy else {_digest(event)})
        if event["payload_digest"] not in expected_digests:
            raise EventStoreError("An immutable event record failed its payload integrity check.")
    except (TypeError, ValueError, UnicodeError) as error:
        raise EventStoreError("An immutable event record failed its payload integrity check.") from error
    try:
        if not isinstance(event["recorded_at"], str):
            raise ValueError("timestamp is not text")
        timestamp = datetime.fromisoformat(event["recorded_at"].replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise EventStoreError("An immutable event record has an invalid timestamp.") from error
    if timestamp.tzinfo is None:
        raise EventStoreError("An immutable event record timestamp must include a timezone.")
    partition = timestamp.astimezone(timezone.utc)
    if list(path.parent.parts[-3:]) != [partition.strftime("%Y"), partition.strftime("%m"), partition.strftime("%d")]:
        raise EventStoreError("An immutable event is stored in the wrong date partition.")
    if is_legacy:
        event["recorded_at_source"] = "legacy_unknown"
    return event


def _find_existing(events_root: Path, identifier: str) -> Path | None:
    matches = []
    for path in events_root.rglob(f"{identifier}.json"):
        if _is_link(path):
            raise EventStoreError("An event lookup encountered an unsafe symbolic link.")
        matches.append(path)
        if len(matches) > 1:
            raise EventStoreError("Duplicate immutable event identifiers exist in the event store.")
    return matches[0] if matches else None


def _publish_new(path: Path, content: bytes) -> bool:
    descriptor, temporary_name = tempfile.mkstemp(prefix=".event-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            return False
        except OSError as error:
            raise EventStoreError("The immutable event could not be published without overwrite.") from error
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def append_event(binding: dict, payload: dict, event_id: str | None = None) -> dict:
    """Publish one immutable event or return the matching prior event on retry."""
    _validate_binding(binding)
    event, digest = _validate_payload(binding, payload, event_id)
    event["payload_digest"] = digest
    events_root = Path(binding["events_root"])
    runtime_root = Path(binding["runtime_root"])
    _ensure_directory(events_root, Path(binding["private_root"]))
    _ensure_directory(runtime_root, Path(binding["private_root"]))
    with _event_lock(binding):
        existing_path = _find_existing(events_root, event["event_id"])
        if existing_path is not None:
            existing = _read_event(existing_path)
            same_payload = existing.get("payload_digest") == digest
            if existing.get("recorded_at_source") == "legacy_unknown":
                timestamp_matches = (event.get("recorded_at") is None
                                     or event.get("recorded_at") == existing.get("recorded_at"))
                legacy_event = dict(event)
                legacy_user = dict(event.get("user", {}))
                legacy_user["login"] = existing["user"]["login"]
                legacy_event["user"] = legacy_user
                same_payload = timestamp_matches and existing.get("payload_digest") in {
                    _legacy_digest(legacy_event), _legacy_digest(legacy_event, include_login=True),
                }
            if not same_payload:
                raise EventConflictError("The event ID already exists with different immutable content.")
            return {"created": False, "event": existing}
        if event["recorded_at"] is None:
            parsed_time = datetime.now(timezone.utc)
            event["recorded_at"] = parsed_time.isoformat()
        else:
            try:
                parsed_time = datetime.fromisoformat(event["recorded_at"].replace("Z", "+00:00"))
                if parsed_time.tzinfo is None:
                    raise ValueError("timezone required")
            except ValueError as error:
                raise EventStoreError("The event timestamp is not valid ISO 8601.") from error
        try:
            stamp = parsed_time.astimezone(timezone.utc)
        except ValueError as error:
            raise EventStoreError("The event timestamp is not valid ISO 8601.") from error
        day_directory = events_root / stamp.strftime("%Y") / stamp.strftime("%m") / stamp.strftime("%d")
        _ensure_directory(day_directory, Path(binding["private_root"]))
        target = day_directory / f"{event['event_id']}.json"
        content = json.dumps(event, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        if len(content) > MAX_EVENT_BYTES:
            raise EventStoreError("The event exceeds the maximum allowed size.")
        if not _publish_new(target, content):
            existing = _read_event(target)
            if existing.get("payload_digest") != digest:
                raise EventConflictError("The event ID already exists with different immutable content.")
            return {"created": False, "event": existing}
        return {"created": True, "event": event}
