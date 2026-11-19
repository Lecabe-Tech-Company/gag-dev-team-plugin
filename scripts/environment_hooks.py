"""Capture supported lifecycle facts without prompts, tool output, or secrets."""
import hashlib
import uuid


def session_context(project, event, harness):
    try:
        from environment_identity import project_binding, resolve_identity
        from environment_projection import read_snapshot
        from event_store import append_event
        from user_rules import policy_snapshot
        binding = project_binding(project, resolve_identity())
        native_session = event.get("session_id")
        session_id = hashlib.sha256(str(native_session).encode()).hexdigest() if isinstance(native_session, str) and native_session else None
        model = {"source": "unknown"}
        # Only a documented top-level host model field is an observation.
        if harness == "claude" and isinstance(event.get("model"), str) and len(event["model"]) <= 120:
            model = {"source": "observed", "observed": event["model"], "provider": "anthropic"}
        append_event(binding, {"event_type": "identity.observed", "data": {"login": binding["user"]["login"]}})
        append_event(binding, {"event_type": "session.started", "session_id": session_id, "agent_id": harness, "model": model,
                               "data": {"coverage": "registered-hook-events-only"}}, "session-" + session_id if session_id else None)
        snapshot = read_snapshot(binding)
        policy_digest = policy_snapshot()["policy_digest"]
        catalog = []
        for extension in snapshot["extensions"]:
            if extension.get("state") == "active" and extension.get("kind") == "skill" and extension.get("review", {}).get("policy_digest") == policy_digest:
                catalog.append({key: extension.get(key) for key in ("extension_id", "name", "digest", "kind")})
        import json
        return ("Private authenticated environment is available. Use ensure-dashboard to verify/start the local dashboard and communicate its protected URL. "
                "Use record-agent-issue for sanitized operational problems. Metrics cover registered events only. "
                "Personal extensions remain subordinate to mandatory plugin policies; load relevant reviewed skills with extensions load. Catalog: "
                + json.dumps(catalog, ensure_ascii=True))
    except Exception:
        return ("The authenticated private environment is unavailable. Verify GitHub CLI authentication and private storage; "
                "do not invent an identity or associate legacy data automatically. No personal extensions were loaded.")


def record_gate_failure(project, event, harness):
    """A gate refusal is a process fact, never automatic evidence of a model error."""
    try:
        from environment_identity import project_binding, resolve_identity
        from event_store import append_event
        binding = project_binding(project, resolve_identity())
        append_event(binding, {"event_type": "issue.opened", "agent_id": harness,
                               "issue_id": str(uuid.uuid4()),
                               "category": "process", "severity": "warning", "attribution": "unknown",
                               "summary": "The pull request gate could not verify required preconditions.",
                               "data": {"code": "pr_gate_refused", "coverage": "registered-hook-events-only"}})
    except Exception:
        pass
