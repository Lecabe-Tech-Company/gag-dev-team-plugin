"""Um evento por chamada; Stop nunca reabre o turno automaticamente."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "hooks/scripts"))
from sdd_gate import deny
from releases import update_project
from harness_adapters import guidance
from user_rules import context_for as user_rule_context
from user_skills import catalog_for as user_skill_catalog
import check_scripta
import graphify_hook
from environment_hooks import session_context, record_gate_failure


def context(message, harness):
    if harness == "cursor":
        return {"additional_context": message}
    if harness == "antigravity":
        return {"injectSteps": [{"systemMessage": {"systemMessage": message}}]}
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message}}


def normalize(event, harness):
    if harness == "antigravity":
        data = event.get("toolCall", {}).get("args", {})
        return {"tool_name": event.get("toolCall", {}).get("name", ""),
                "tool_input": {"command": data.get("CommandLine", ""), **data},
                "cwd": data.get("Cwd", event.get("workspacePaths", [str(ROOT.parent.parent)])[0])}
    data = event.get("tool_input", {})
    if isinstance(data, dict):
        event = dict(event, cwd=data.get("workdir", data.get("working_directory", event.get("cwd"))))
    return event


def main():
    harness, event_name = sys.argv[1:3]
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw_event = stream.read()
    if isinstance(raw_event, bytes):
        raw_event = raw_event.decode("utf-8")
    event = json.loads(raw_event)
    project = ROOT.parent.parent
    if harness == "portable" and event_name == "SessionStart":
        project = event.get("cwd") or event.get("workingDirectory") or event.get("workspace")
        messages = []
        if not isinstance(project, str) or not project:
            messages.append("The active project path is unavailable; no private project rules or user skills were applied.")
        else:
            messages.append(session_context(project, event, harness))
            try:
                messages.append(user_rule_context(project, ROOT)["context"])
            except Exception:
                messages.append("The complete private project-rule snapshot is unavailable; no private rules were applied. Plugin policies remain in force.")
            try:
                messages.append(user_skill_catalog(project, ROOT)["context"])
            except Exception:
                messages.append("The private user-skill catalog is unavailable; no private skills were applied. Plugin policies remain in force.")
        print(json.dumps(context("\n\n".join(messages), "codex"), ensure_ascii=True))
        return
    if event_name == "UserPromptSubmit":
        # Native prompt hooks cannot reliably distinguish consent from quoted or
        # ambiguous text. Keep their output neutral; the orchestrator reads context.
        print(json.dumps({"continue": True} if harness == "cursor" else {}))
        return
    if event_name in ("SessionStart", "Stop"):
        changed = None
        # Antigravity informa se tarefas paralelas ainda estão ativas.
        if not (harness == "antigravity" and event_name == "Stop" and event.get("fullyIdle") is False):
            try:
                changed = update_project(project)
            except Exception:
                changed = None  # Uma falha de rede não remove nem quebra a instalação vigente.
        if event_name == "Stop":
            print(json.dumps({"decision": "stop"} if harness == "antigravity" else {}))
            return
        messages = [guidance()]
        messages.append(session_context(project, event, harness))
        try:
            messages.append(user_rule_context(project, ROOT)["context"])
        except Exception:
            messages.append(
                "The complete private project-rule snapshot is unavailable; no private rules were applied. "
                "All GAG Dev Team plugin policies remain in force."
            )
        try:
            messages.append(user_skill_catalog(project, ROOT)["context"])
        except Exception:
            messages.append(
                "The private user-skill catalog is unavailable; no private skills were applied. "
                "All GAG Dev Team plugin policies remain in force."
            )
        if changed and changed.get("updated"):
            messages.append("O plugin foi atualizado para " + changed["version"] + ". Novos perfis serão recarregados na próxima sessão.")
        output = check_scripta.output_for(check_scripta.inspect_access(ROOT))
        messages.append(output["hookSpecificOutput"]["additionalContext"])
        if (ROOT.parent / "scripta-token").is_file():
            try:
                graphify_hook.ensure_graphify()
            except Exception:
                messages.append("A preparação do Graphify está pendente; confira o terminal de configuração.")
        print(json.dumps(context("\n\n".join(messages), harness), ensure_ascii=True))
        return
    try:
        request = graphify_hook.pr_request(normalize(event, harness))
        if request:
            message = graphify_hook.analyze_pr(request, graphify_hook.ensure_graphify())
            if harness in ("codex", "claude"):
                print(json.dumps(graphify_hook.respond("PreToolUse", message)))
            else:
                print("{}")
            return
        print("{}")
    except graphify_hook.GateError as error:
        record_gate_failure(project, event, harness)
        print(json.dumps(deny(str(error), harness), ensure_ascii=True))
    except Exception:
        record_gate_failure(project, event, harness)
        print(json.dumps(deny("PR bloqueado: conclua a análise Graphify e os testes da feature e dos fluxos relacionados antes da abertura.", harness)))


if __name__ == "__main__":
    main()
