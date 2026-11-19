"""Replay private events into the dashboard's read-only JSON contract."""
from __future__ import annotations

import json
import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from event_store import EventStoreError, _read_event
except ModuleNotFoundError:
    from scripts.event_store import EventStoreError, _read_event


def _timestamp(event: dict) -> str:
    value = event.get("recorded_at")
    if isinstance(value, str):
        return value
    return ""


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise EventStoreError("An event timestamp is not valid ISO 8601.") from error
    if parsed.tzinfo is None:
        raise EventStoreError("An event timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _matches(event: dict, filters: dict) -> bool:
    event_time = _timestamp(event)
    instant = _instant(event_time)
    period = filters.get("period")
    if period and period != "all":
        ranges = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}
        if period not in ranges:
            raise EventStoreError("Snapshot period must be 1d, 7d, 30d, 90d, or all.")
        try:
            recorded = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError:
            return False
        if recorded < datetime.now(timezone.utc) - timedelta(days=ranges[period]):
            return False
    for name in ("from", "to"):
        boundary = filters.get(name)
        if boundary:
            boundary_instant = _instant(boundary)
            if (instant < boundary_instant if name == "from" else instant > boundary_instant):
                return False
    if filters.get("event_type") and event.get("event_type") != filters["event_type"]:
        return False
    if filters.get("category") and event.get("category") != filters["category"]:
        return False
    model_filter = filters.get("model")
    model = event.get("model", {})
    if model_filter and model_filter not in {model.get("observed"), model.get("requested")}:
        return False
    return True


def _safe_event_paths(events_root: Path):
    if events_root.is_symlink() or (hasattr(events_root, "is_junction") and events_root.is_junction()):
        raise EventStoreError("The private event root is unsafe.")
    for path in events_root.rglob("*.json"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise EventStoreError("The event history contains a symbolic link.")
        if path.is_file():
            yield path


def _load_events(binding: dict, filters: dict) -> list[dict]:
    root = Path(binding["private_root"]).resolve(strict=True)
    events_root = Path(binding["events_root"])
    try:
        events_root.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as error:
        raise EventStoreError("The private event root escapes its project binding.") from error
    if not events_root.exists():
        return []
    events = []
    for path in _safe_event_paths(events_root):
        event = _read_event(path)
        event_user = event.get("user") or {}
        bound_user = binding["user"]
        if (event.get("project_id") != binding["project_id"]
                or event_user.get("provider") != bound_user.get("provider")
                or event_user.get("host") != bound_user.get("host")
                or event_user.get("id") != bound_user.get("id")):
            raise EventStoreError("An event does not match the selected account and project binding.")
        if _matches(event, filters):
            events.append(event)
    return sorted(events, key=lambda event: (_instant(_timestamp(event)), event.get("event_id", "")))


def _latest_by_id(events: list[dict], event_types: set[str], key: str) -> list[dict]:
    latest = {}
    for event in events:
        if event.get("event_type") not in event_types:
            continue
        data = event.get("data") or {}
        record = data.get("record") if isinstance(data, dict) else None
        identifier = record.get(key) if isinstance(record, dict) else event.get("issue_id")
        if not isinstance(identifier, str) or not identifier:
            continue
        latest[identifier] = (event, record if isinstance(record, dict) else {})
    values = []
    for identifier, (event, record) in latest.items():
        result = dict(record)
        result.setdefault("id", identifier)
        result.setdefault("updated_at", _timestamp(event))
        result.setdefault("status", "active")
        values.append(result)
    return sorted(values, key=lambda item: (item.get("updated_at", ""), item.get("id", "")), reverse=True)


def _project_issues(events: list[dict]) -> list[dict]:
    issues = {}
    for event in events:
        event_type = event.get("event_type")
        issue_id = event.get("issue_id")
        if not isinstance(issue_id, str) or not issue_id:
            continue
        data = event.get("data") or {}
        record = data.get("issue") if isinstance(data, dict) else None
        if event_type == "issue.opened":
            record = record if isinstance(record, dict) else {}
            issues.setdefault(issue_id, {"id": issue_id, "status": "open", "causes": [], "attempt_ids": []})
            current = issues[issue_id]
            current.update({key: value for key, value in record.items() if key not in {"id", "status"}})
            current.update({
                "category": event.get("category"), "severity": event.get("severity"),
                "attribution": event.get("attribution"), "summary": event.get("summary"),
                "opened_at": current.get("opened_at", _timestamp(event)), "updated_at": _timestamp(event),
                "model": event.get("model"), "causes": event.get("causes", []),
            })
            attempt_id = event.get("attempt_id")
            if attempt_id:
                current["attempt_ids"] = sorted(set(current.get("attempt_ids", [])) | {attempt_id})
        elif event_type in {"issue.resolved", "issue.corrected"}:
            current = issues.setdefault(issue_id, {"id": issue_id, "causes": [], "attempt_ids": []})
            current["status"] = "resolved" if event_type == "issue.resolved" else current.get("status", "open")
            current["updated_at"] = _timestamp(event)
            if isinstance(record, dict):
                current.update({key: value for key, value in record.items() if key != "id"})
            current["causes"] = sorted(set(current.get("causes", [])) | set(event.get("causes", [])))
    return sorted(issues.values(), key=lambda item: (item.get("updated_at", ""), item["id"]), reverse=True)


def _project_sessions(events: list[dict]) -> list[dict]:
    sessions = {}
    for event in events:
        if event.get("event_type") not in {"session.started", "session.ended"}:
            continue
        session_id = event.get("session_id")
        if not session_id:
            continue
        session = sessions.setdefault(session_id, {"id": session_id, "started_at": None, "ended_at": None, "agent_id": None})
        if event["event_type"] == "session.started":
            session["started_at"] = session["started_at"] or _timestamp(event)
            session["agent_id"] = event.get("agent_id") or session["agent_id"]
        else:
            session["ended_at"] = _timestamp(event)
    return sorted(sessions.values(), key=lambda item: (item["started_at"] or "", item["id"]), reverse=True)


def _project_models(events: list[dict], issues: list[dict]) -> list[dict]:
    attempts: dict[str, dict] = {}
    source_rank = {"unknown": 0, "configured": 1, "declared": 2, "observed": 3}
    for event in events:
        if event.get("event_type") != "attempt.recorded" or not event.get("attempt_id"):
            continue
        attempt_id = event["attempt_id"]
        existing = attempts.get(attempt_id)
        if existing is None or source_rank.get(event.get("model", {}).get("source", "unknown"), 0) > source_rank.get(existing.get("model", {}).get("source", "unknown"), 0):
            attempts[attempt_id] = event
    issue_by_id = {issue["id"]: issue for issue in issues}
    model_rows = {}
    for event in attempts.values():
        model = event.get("model") or {}
        key = (model.get("provider"), model.get("observed"), model.get("requested"), model.get("source", "unknown"))
        row = model_rows.setdefault(key, {
            "provider": key[0], "observed": key[1], "requested": key[2], "source": key[3],
            "attempt_count": 0, "issue_ids": set(), "confirmed_model_issue_ids": set(),
        })
        row["attempt_count"] += 1
        issue_id = event.get("issue_id")
        if issue_id in issue_by_id:
            row["issue_ids"].add(issue_id)
            if issue_by_id[issue_id].get("attribution") == "confirmed_model":
                row["confirmed_model_issue_ids"].add(issue_id)
    result = []
    for row in model_rows.values():
        row["issue_count"] = len(row.pop("issue_ids"))
        row["confirmed_model_issue_count"] = len(row.pop("confirmed_model_issue_ids"))
        result.append(row)
    return sorted(result, key=lambda item: (item["provider"] or "", item["observed"] or item["requested"] or "", item["source"]))


def _revision(events: list[dict]) -> str:
    identifiers = sorted(event.get("event_id", "") for event in events)
    return hashlib.sha256("\n".join(identifiers).encode("utf-8")).hexdigest()


def _public_event(event: dict) -> dict:
    """Remove local paths and raw rollout identifiers from dashboard event output."""
    result = dict(event)
    data = result.get("data")
    if result.get("event_type", "").startswith("token."):
        for field in ("session_id", "attempt_id", "task_id"):
            result[field] = None
    if isinstance(data, dict):
        private_keys = {"source_root", "thread_id", "session_id", "turn_id", "root_turn_id",
                        "response_id", "source_key_digest"}
        result["data"] = {key: value for key, value in data.items() if key not in private_keys}
    return result


def _project_extensions(events: list[dict]) -> list[dict]:
    latest = {}
    default_states = {
        "extension.discovered": "discovered", "extension.downloaded": "downloaded",
        "extension.reviewed": "reviewed", "extension.installed": "installed",
        "extension.activated": "active", "extension.failed": "failed",
        "extension.deactivated": "deactivated", "extension.removed": "deactivated",
    }
    allowed_states = {"requested", "rejected", "pending_profile", "pending_host", "pending_auth_or_trust", "pending_auth", "pending_trust", "pending_restart", "pending_verification", "pending_review", "reviewed", "installed", "active", "failed", "deactivated", "discovered", "downloaded", "unknown"}
    for event in events:
        if not event.get("event_type", "").startswith("extension."):
            continue
        data = event.get("data") or {}
        extension = data.get("extension") if isinstance(data, dict) else None
        if not isinstance(extension, dict) and isinstance(data, dict) and (data.get("extension_id") or data.get("id")):
            extension = data
        if not isinstance(extension, dict):
            continue
        identifier = extension.get("extension_id") or extension.get("id")
        if not isinstance(identifier, str) or not identifier:
            continue
        state = extension.get("state")
        if state not in allowed_states:
            state = default_states.get(event.get("event_type"), "unknown")
        previous = latest.get(identifier, {})
        preserved = {}
        if previous.get("digest") == extension.get("digest"):
            preserved = previous
        else:
            preserved = {key: previous[key] for key in ("name", "kind", "source") if key in previous}
        latest[identifier] = {
            **preserved,
            **extension,
            "id": identifier,
            "extension_id": identifier,
            "state": state,
            "updated_at": _timestamp(event),
            "event_id": event.get("event_id"),
        }
    return sorted(latest.values(), key=lambda item: (item["updated_at"], item["id"]), reverse=True)


def read_snapshot(binding: dict, filters: dict | None = None) -> dict:
    """Replay scoped events into stable dashboard sections without writing history."""
    filters = filters or {}
    allowed_filters = {"from", "to", "event_type", "category", "model", "period", "status", "limit", "cursor", "goal_id", "agent_id"}
    if not isinstance(filters, dict) or set(filters) - allowed_filters:
        raise EventStoreError("The snapshot filter set is invalid.")
    period_filter = filters.get("period")
    if period_filter is not None and (not isinstance(period_filter, str)
                                      or period_filter not in {"all", "1d", "7d", "30d", "90d"}):
        raise EventStoreError("Snapshot period must be 1d, 7d, 30d, 90d, or all.")
    for name in ("from", "to"):
        value = filters.get(name)
        if value is not None:
            if not isinstance(value, str):
                raise EventStoreError(f"Snapshot {name} filter must be an ISO 8601 timestamp.")
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise EventStoreError(f"Snapshot {name} filter must be an ISO 8601 timestamp.") from error
            if parsed.tzinfo is None:
                raise EventStoreError(f"Snapshot {name} filter must include a timezone.")
    for name in ("event_type", "category", "model", "status", "cursor", "goal_id", "agent_id"):
        value = filters.get(name)
        if value is not None and not isinstance(value, str):
            raise EventStoreError(f"Snapshot {name} filter must be text.")
    full_events = _load_events(binding, {})
    events = [event for event in full_events if _matches(event, filters)]
    projected_rules = _latest_by_id(full_events, {"rule.versioned", "rule.deactivated"}, "id")
    projected_skills = _latest_by_id(full_events, {"skill.versioned", "skill.deactivated"}, "id")
    issues = _project_issues(full_events)
    extensions = _project_extensions(full_events)
    lower_bound = filters.get("from")
    upper_bound = filters.get("to")
    period = filters.get("period")
    period_days = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}.get(period)
    period_start = datetime.now(timezone.utc) - timedelta(days=period_days) if period_days else None
    def matches_record_time(value):
        if not isinstance(value, str):
            return False
        try:
            instant = _instant(value)
        except EventStoreError:
            return False
        if lower_bound and instant < _instant(lower_bound):
            return False
        if upper_bound and instant > _instant(upper_bound):
            return False
        if period_start:
            if instant < period_start:
                return False
        return True
    if lower_bound or upper_bound or period:
        issues = [item for item in issues if matches_record_time(item.get("updated_at"))]
        extensions = [item for item in extensions if matches_record_time(item.get("updated_at"))]
        sessions = _project_sessions(full_events)
        sessions = [item for item in sessions if matches_record_time(item.get("started_at"))]
    else:
        sessions = _project_sessions(full_events)
    status_filter = filters.get("status")
    if status_filter:
        projected_rules = [item for item in projected_rules if item.get("status") == status_filter]
        projected_skills = [item for item in projected_skills if item.get("status") == status_filter]
        issues = [item for item in issues if item.get("status") == status_filter]
        extensions = [item for item in extensions if item.get("state") == status_filter]
    models = _project_models(events, issues)
    try:
        from token_usage import usage_snapshot
    except ModuleNotFoundError:
        from scripts.token_usage import usage_snapshot
    usage_filters = {key: value for key, value in filters.items()
                     if key in {"period", "from", "to", "model", "goal_id", "agent_id"}}
    token_usage = usage_snapshot(binding, usage_filters, full_events)
    latest_identity = next((event for event in reversed(full_events) if event.get("event_type") == "identity.observed"), None)
    try:
        metadata = json.loads((Path(__file__).resolve().parents[1] / "plugin.json").read_text(encoding="utf-8"))
        plugin_version = metadata.get("version") if isinstance(metadata.get("version"), str) else None
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        plugin_version = None
    environment = {
        "host": binding["user"]["host"], "project_id": binding["project_id"],
        "plugin_version": plugin_version, "last_seen_at": _timestamp(latest_identity) if latest_identity else None,
    }
    capabilities = {"events": True, "model_metrics": True, "legacy_import": True}
    limit = filters.get("limit", 500)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise EventStoreError("Snapshot limit must be an integer from 1 to 500.")
    cursor = filters.get("cursor")
    if cursor is not None:
        if not isinstance(cursor, str) or not cursor:
            raise EventStoreError("Snapshot cursor must be an event identifier.")
        cursor_index = next((index for index, event in enumerate(events) if event.get("event_id") == cursor), None)
        if cursor_index is None:
            raise EventStoreError("Snapshot cursor does not belong to the selected event history.")
        events = events[cursor_index + 1:]
    displayed = events[:limit]
    next_cursor = displayed[-1]["event_id"] if len(events) > limit else None
    return {
        "schema_version": 1,
        "binding": {"project_id": binding["project_id"], "user": binding["user"]},
        "plugin_version": plugin_version,
        "revision": _revision(full_events),
        "as_of": datetime.now(timezone.utc).isoformat(),
        "capabilities": capabilities,
        "environment": environment,
        "rules": projected_rules,
        "skills": projected_skills,
        "sessions": sessions,
        "issues": issues,
        "models": models,
        "token_usage": token_usage,
        "extensions": extensions,
        "diagnostics": [],
        "events": [_public_event(event) for event in displayed],
        "next_cursor": next_cursor,
    }
