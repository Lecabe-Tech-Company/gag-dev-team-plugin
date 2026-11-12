"""Estado auxiliar de SDD; autorização continua sendo contextual do orquestrador."""
import json
from datetime import datetime, timezone

from project_install import atomic_write, ignore_private_data, project_root, safe_path


def location(project):
    return safe_path(project_root(project), ".gag-dev-team/sdd.json")


def identity(reference, version):
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 300:
        raise ValueError("Informe a referência do SDD no Scripta.")
    if not isinstance(version, (str, int)) or isinstance(version, bool) or not str(version).isdigit() or int(version) < 1:
        raise ValueError("Informe a versão concreta do SDD.")
    return reference.strip(), str(version).strip()


def _read_state(path):
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def _write_state(path, state):
    atomic_write(path, (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode(), private=True)


def _prepare_private_state(project):
    root = project_root(project)
    if (root / ".git").exists():
        ignore_private_data(root)
    return root


def declare_sdd(project, reference, version):
    reference, version = identity(reference, version)
    project = _prepare_private_state(project)
    path = location(project)
    previous = _read_state(path)
    if (previous.get("reference"), previous.get("version")) == (reference, version):
        return previous

    # Evidence only belongs to the exact declared identity. A new version starts clean.
    state = {"reference": reference, "version": version, "approved": False}
    _write_state(path, state)
    return state


def record_sdd_approval(project, reference, version, evidence, recorded_by):
    """Record literal user evidence supplied by the orchestrator; never infer consent."""
    reference, version = identity(reference, version)
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("Informe a evidência literal do aceite do usuário.")
    if not isinstance(recorded_by, str) or not recorded_by.strip():
        raise ValueError("Informe quem registrou a evidência.")

    project = _prepare_private_state(project)
    path = location(project)
    state = _read_state(path)
    if (state.get("reference"), state.get("version")) != (reference, version):
        state = {}
    state.update(reference=reference, version=version, approved=True,
                 approved_by="user", recorded_by=recorded_by.strip(),
                 evidence=evidence,
                 recorded_at=datetime.now(timezone.utc).isoformat(),
                 approval_source="contextual-user-evidence")
    _write_state(path, state)
    return state


def approve_sdd(project, reference, version, explicit=False):
    """Compatibility alias for a direct yes/no terminal confirmation."""
    reference, version = identity(reference, version)
    if not explicit:
        raise ValueError("Confirme a aprovação do SDD no terminal.")
    project = _prepare_private_state(project)
    path = location(project)
    state = _read_state(path)
    if (state.get("reference"), state.get("version")) != (reference, version):
        state = {}
    state.update(reference=reference, version=version, approved=True,
                 approved_by="user", recorded_by="terminal",
                 recorded_at=datetime.now(timezone.utc).isoformat(),
                 approval_source="terminal-confirmation")
    _write_state(path, state)
    return state


def deny(message, harness):
    if harness == "antigravity":
        return {"decision": "deny", "reason": message}
    if harness == "cursor":
        return {"permission": "deny", "user_message": message, "agent_message": message}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
            "permissionDecision": "deny", "permissionDecisionReason": message}}


def gate(event, project, harness="codex"):
    """Compatibility API: approval metadata never blocks tools or the Graphify gate."""
    return {}


def record_user_approval(project, prompt):
    """Compatibility API: a prompt hook cannot infer or record user intent."""
    return False
