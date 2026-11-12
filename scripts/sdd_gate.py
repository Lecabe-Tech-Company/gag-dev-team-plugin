"""Gate local de desenvolvimento vinculado à referência e versão do SDD."""
import json
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path

from project_install import atomic_write, project_root, safe_path


def location(project):
    return safe_path(project_root(project), ".gag-dev-team/sdd.json")


def identity(reference, version):
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 300:
        raise ValueError("Informe a referência do SDD no Scripta.")
    if not isinstance(version, (str, int)) or isinstance(version, bool) or not str(version).isdigit() or int(version) < 1:
        raise ValueError("Informe a versão concreta do SDD.")
    return reference.strip(), str(version).strip()


def declare_sdd(project, reference, version):
    reference, version = identity(reference, version)
    path = location(project)
    previous = json.loads(path.read_text()) if path.exists() else {}
    if (previous.get("reference"), previous.get("version")) == (reference, version):
        return previous
    state = {"reference": reference, "version": version, "approved": False}
    atomic_write(path, (json.dumps(state, indent=2) + "\n").encode())
    return state


def approve_sdd(project, reference, version, explicit=False):
    reference, version = identity(reference, version)
    path = location(project)
    state = json.loads(path.read_text()) if path.exists() else {}
    if not explicit:
        raise ValueError("A aprovação exige confirmação explícita do usuário.")
    if (state.get("reference"), state.get("version")) != (reference, version):
        raise ValueError("Aprovação não corresponde à referência e versão declaradas.")
    state.update(approved=True, approval_source="user-confirmation",
                 approved_at=datetime.now(timezone.utc).isoformat())
    atomic_write(path, (json.dumps(state, indent=2) + "\n").encode())
    return state


def deny(message, harness):
    if harness == "antigravity":
        return {"decision": "deny", "reason": message}
    if harness == "cursor":
        return {"permission": "deny", "user_message": message, "agent_message": message}
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
            "permissionDecision": "deny", "permissionDecisionReason": message}}


def safe_command(command):
    if not isinstance(command, str) or any(mark in command for mark in (";", "&&", "||", "\n", "|", ">", "<", "`", "$(")):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    name = Path(tokens[0]).name.lower()
    if "approve-sdd" in tokens:
        return False
    if any(t.startswith(("--output", "--pre", "--ext-diff")) for t in tokens):
        return False
    if name in ("cat", "ls", "pwd", "rg", "grep", "head", "tail", "get-content", "get-childitem", "select-string"):
        return True
    if name == "find":
        return not any(token in tokens for token in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"))
    if name == "git" and len(tokens) > 1:
        return tokens[1] in ("status", "diff", "log", "show", "rev-parse", "ls-files", "ls-tree")
    # Configuração e declaração do SDD não são implementação da feature.
    if any(Path(t).name in ("gag_dev_team.py", "gag-dev-team", "gag-dev-team.cjs") for t in tokens):
        return any(t in tokens for t in ("install", "configure", "update", "declare-sdd", "--help"))
    return False


def gate(event, project, harness="codex"):
    if harness == "antigravity":
        event = {"tool_name": event.get("toolCall", {}).get("name", ""),
                 "tool_input": event.get("toolCall", {}).get("args", {})}
    tool = str(event.get("tool_name", event.get("toolName", event.get("tool", "")))).lower()
    data = event.get("tool_input", event.get("toolInput", event.get("input", {}))) or {}
    if "docs_" in tool:
        return {}
    command = data.get("command", data.get("cmd", data.get("CommandLine", ""))) if isinstance(data, dict) else ""
    execution = any(t in tool for t in ("bash", "exec", "shell", "terminal", "run_command"))
    mutation = any(t in tool for t in ("write", "edit", "replace", "delete", "apply_patch", "create_file"))
    if execution and safe_command(command):
        return {}
    if not execution and not mutation:
        return {}
    path = location(project)
    try:
        state = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(state, dict):
            raise ValueError("Estado de aprovação inválido.")
        if state:
            identity(state.get("reference"), state.get("version"))
    except (OSError, ValueError, TypeError):
        return deny("Estado de aprovação inválido. O orquestrador deve regularizar o SDD e obter o aceite do usuário.", harness)
    if state.get("approved") is True and state.get("approval_source") == "user-confirmation":
        return {}
    description = "SDD " + str(state.get("reference", "não informado")) + " v" + str(state.get("version", "?"))
    return deny("Desenvolvimento bloqueado: " + description
                + " ainda não foi aprovado explicitamente pelo usuário. "
                "O orquestrador deve apresentar o SDD do Scripta e obter o aceite da versão vigente. "
                "Leitura, planejamento e configuração podem continuar; não automatize a própria aprovação.", harness)

def record_user_approval(project, prompt):
    """Somente o evento nativo de texto do usuário chama esta função."""
    path = location(project)
    try:
        state = json.loads(path.read_text()) if path.exists() else {}
        reference, current_version = identity(state.get("reference"), state.get("version"))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    if not isinstance(prompt, str):
        return False
    expected = "Aprovar " + reference + " v" + current_version
    if prompt.strip().casefold() != expected.casefold():
        return False
    if state.get("approved") is True:
        return True
    approve_sdd(project, reference, current_version, explicit=True)
    return True
