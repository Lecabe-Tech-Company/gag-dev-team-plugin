"""Formatos nativos separados; nenhum schema de um cliente é copiado para outro."""
import json
import base64
import os
import re
import tomllib
from pathlib import Path

HARNESS_NAMES = {"codex": "Codex", "claude": "Claude Code", "cursor": "Cursor", "antigravity": "Antigravity"}
MODELS = {
    "claude": {"gag-orquestrador-planejador": "sonnet", "gag-desenvolvedor": "haiku",
               "gag-investigador-advisor": "opus", "gag-revisor-qa": "opus", "gag-documentador": "haiku"},
    "antigravity": {"gag-orquestrador-planejador": "pro", "gag-desenvolvedor": "flash",
               "gag-investigador-advisor": "pro", "gag-revisor-qa": "pro", "gag-documentador": "flash"},
}
BOOTSTRAP = (
    "/*GAG_DEV_TEAM*/const fs=require('node:fs'),p=require('node:path');let r=process.cwd();"
    "while(!fs.existsSync(p.join(r,'.gag-dev-team','install.json'))){const n=p.dirname(r);"
    "if(n===r)throw Error('Execute gag-dev-team install no projeto');r=n;}"
)



def bootstrap(project=None):
    if project is None:
        return BOOTSTRAP
    roots = [str(project)]
    distro = os.environ.get("WSL_DISTRO_NAME")
    if distro and str(project).startswith("/"):
        roots.append("\\\\wsl.localhost\\" + distro + str(project).replace("/", "\\"))
    encoded = base64.b64encode(json.dumps(roots).encode()).decode()
    return (
        "/*GAG_DEV_TEAM*/const fs=require('node:fs'),p=require('node:path');let r;"
        "for(const c of [process.cwd(),...JSON.parse(Buffer.from('" + encoded + "','base64').toString())]){"
        "let x=c;while(!fs.existsSync(p.join(x,'.gag-dev-team','install.json'))){"
        "const n=p.dirname(x);if(n===x)break;x=n;}"
        "if(fs.existsSync(p.join(x,'.gag-dev-team','install.json'))){r=x;break;}}"
        "if(!r)throw Error('Execute gag-dev-team install no projeto');"
    )

def invocation(relative, expression="", project=None):
    # Aspas duplas e código sem expansão de shell: funciona em CMD e shells POSIX.
    code = bootstrap(project) + "require(p.join(r,'.gag-dev-team','plugin'," + json.dumps(relative) + "))" + expression
    return "node -e " + json.dumps(code)


def mcp_bridge(project=None):
    code = bootstrap(project) + "require(p.join(r,'.gag-dev-team','plugin','mcp/scripta_bridge.cjs'));"
    return {"command": "node", "args": ["-e", code]}


def guidance():
    return (
        "O Orquestrador / Planejador do GAG Dev Team é o interlocutor inicial e permanente do usuário. "
        "Antes de implementar ou delegar, confira no contexto real da conversa se o usuário autorizou claramente "
        "o escopo e a versão vigente do SDD do Scripta. Silêncio, negativa, ambiguidade ou aceite de outro escopo "
        "não autorizam. Apresente o SDD com seus sete subtítulos. Não exija frase padrão, mensagem isolada, "
        "ordem entre aceite e declaração ou repetição de aceite já claro. "
        "Declare a referência e a versão por declare-sdd. Mudança material de escopo exige novo aceite. "
        "O orquestrador pode registrar uma fala literal já dada pelo usuário com approve-sdd --reference REF "
        "--sdd-version VERSAO --evidence TEXTO --recorded-by IDENTIFICACAO. Esse registro é auxiliar: não invente "
        "fala nem trate falha/ausência/corrupção do registro como revogação do aceite real. Confirmação terminal "
        "exige ação direta da pessoa e não representa fala original. O hook de prompt não classifica nem aprova "
        "texto. Dev e orquestrador usam o advisor; QA escreve os testes.\n"
        "Use Caveman por padrão nas respostas, preservando idioma e dados técnicos; respeite normal mode/stop caveman. "
        "Não comprima código, documentação ou SDDs persistidos.\n"
        "Siga .agents/skills/development-workflow/SKILL.md e as skills sdd-planning, sdd-development e sdd-qa. "
        "Use Graphify para código, Scripta/renew-it para documentação interna e Context7 para bibliotecas. "
        "Não execute merge automatizado."
    )


def build(project, runtime, source, harnesses):
    from project_install import read, block, BEGIN, END, AGENT_BEGIN, AGENT_END
    managed, merged = {}, {}
    profiles = {p.stem: tomllib.loads(p.read_text(encoding="utf-8")) for p in (source / "agents").glob("gag-*.toml")}
    role_map = {}

    def json_file(path):
        return json.loads(read(project / path, "{}"))

    def put_json(path, value):
        merged[path] = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()

    def hook(event, harness):
        return invocation("bin/runtime.cjs", ".hook(" + json.dumps(harness) + "," + json.dumps(event) + ")", project=project)

    def mcp_json(path):
        value = json_file(path)
        servers = value.setdefault("mcpServers", {})
        remote = {"url": "https://mcp.context7.com/mcp/oauth"}
        if harness == "claude":
            remote["type"] = "http"
        elif harness == "antigravity":
            remote = {"serverUrl": remote["url"]}
        for name, config in {"docs": mcp_bridge(project), "context7": remote}.items():
            old = servers.get(name)
            if old and "GAG_DEV_TEAM" not in json.dumps(old) and old != config:
                raise ValueError(f"MCP {name} já configurado em {path}; preserve e resolva a colisão.")
            servers[name] = config
        put_json(path, value)

    common = block(read(project / "AGENTS.md"), AGENT_BEGIN, AGENT_END,
                   AGENT_BEGIN + "\n" + guidance() + "\n" + AGENT_END)
    merged["AGENTS.md"] = common.encode()
    mode = json_file(".caveman.json")
    mode["defaultMode"] = "caveman"
    put_json(".caveman.json", mode)

    for harness in harnesses:
        role_map[harness] = {}
        for name, profile in profiles.items():
            effort = profile["model_reasoning_effort"]
            model = profile["model"]
            if harness == "claude":
                model = MODELS[harness][name]
            elif harness == "antigravity":
                model = MODELS[harness][name]
            role_map[harness][name] = {"model": model, "requested_reasoning": effort,
                "native_reasoning": effort if harness in ("codex", "cursor") or (harness == "claude" and model != "haiku") else None}
            if harness == "codex":
                managed[".codex/agents/" + name + ".toml"] = (source / "agents" / (name + ".toml")).read_bytes()
                continue
            if harness == "cursor":
                model = model + "[effort=" + effort + "]"
            lines = ["---", "name: " + name, "description: " + json.dumps(profile["description"])]
            lines.append("model: " + json.dumps(model))
            if harness == "claude" and model != "haiku":
                lines.append("effort: " + effort)
            if harness == "antigravity":
                is_main = name == "gag-orquestrador-planejador"
                lines.extend(["mainAgent: " + str(is_main).lower(), "subagent: " + str(not is_main).lower()])
            lines.extend(["---", "", profile["developer_instructions"], "",
                          "Identidade e aprovação: " + guidance(),
                          "Raciocínio solicitado para esta função: " + effort + ". "
                          "Não presuma equivalência exata de esforço entre provedores ou disponibilidade de modelo."])
            directory = {"claude": ".claude/agents", "cursor": ".cursor/agents", "antigravity": ".agents/agents"}[harness]
            managed[directory + "/" + name + ".md"] = ("\n".join(lines) + "\n").encode()

        # Skills nativas de cada editor; .agents/skills é comum ao Codex/Antigravity.
        if harness in ("claude", "cursor"):
            for path in (source / "skills").rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.name != ".gitkeep":
                    managed["." + harness + "/skills/" + path.relative_to(source / "skills").as_posix()] = path.read_bytes()

        if harness == "codex":
            text = read(project / ".codex/config.toml")
            original = tomllib.loads(text)
            root_model = original.get("model", "gpt-6.1-terra")
            root_effort = original.get("model_reasoning_effort", "low")
            unmanaged = block(text, BEGIN, END, "") if BEGIN in text else text
            config = tomllib.loads(unmanaged)
            if any(key in config.get("mcp_servers", {}) for key in ("docs", "context7")):
                raise ValueError("MCP docs/context7 já configurado fora do bloco GAG; preserve e resolva a colisão.")
            # Retira apenas os defaults de modelo da raiz, expressamente configurados pelo instalador.
            header = re.search(r"(?m)^\s*\[", unmanaged)
            split = header.start() if header else len(unmanaged)
            top = re.sub(r"(?m)^(?:model|model_reasoning_effort)\s*=.*\n?", "", unmanaged[:split])
            body = (
                f'{BEGIN}\nmodel = {json.dumps(root_model)}\nmodel_reasoning_effort = {json.dumps(root_effort)}\n'
                '[mcp_servers.docs]\nurl = "https://scripta-mcp.lecabe.com.br/mcp"\n'
                'http_headers_helper = ' + json.dumps(invocation("mcp/scripta_headers.cjs", project=project)) + '\n'
                '[mcp_servers.context7]\nurl = "https://mcp.context7.com/mcp/oauth"\n' + END
            )
            text = top.rstrip() + "\n\n" + body + "\n\n" + unmanaged[split:].lstrip()
            tomllib.loads(text)
            merged[".codex/config.toml"] = text.encode()
            config = json_file(".codex/hooks.json")
            events = config.setdefault("hooks", {})
            for event in ("SessionStart", "Stop", "PreToolUse", "UserPromptSubmit"):
                events[event] = [g for g in events.get(event, [])
                                 if not str(g.get("description", "")).startswith("GAG Dev Team:")
                                 and "GAG_DEV_TEAM" not in json.dumps(g)]
                events[event].append({"description": "GAG Dev Team: " + event,
                    "hooks": [{"type": "command", "command": hook(event, harness), "timeout": 300}]})
            put_json(".codex/hooks.json", config)

        elif harness == "claude":
            mcp_json(".mcp.json")
            config = json_file(".claude/settings.json")
            config["agent"] = "gag-orquestrador-planejador"
            config.setdefault("model", "sonnet")
            events = config.setdefault("hooks", {})
            for event in ("SessionStart", "Stop", "PreToolUse", "UserPromptSubmit"):
                events[event] = [g for g in events.get(event, []) if "GAG_DEV_TEAM" not in json.dumps(g)]
                events[event].append({"hooks": [{"type": "command", "command": hook(event, harness), "timeout": 300}]})
            put_json(".claude/settings.json", config)
            merged["CLAUDE.md"] = block(read(project / "CLAUDE.md"), AGENT_BEGIN, AGENT_END,
                AGENT_BEGIN + "\n" + guidance().replace(".agents/skills", ".claude/skills") + "\n" + AGENT_END).encode()

        elif harness == "cursor":
            mcp_json(".cursor/mcp.json")
            config = json_file(".cursor/hooks.json")
            config["version"] = 1
            events = config.setdefault("hooks", {})
            for native, event in (("sessionStart", "SessionStart"), ("stop", "Stop"), ("preToolUse", "PreToolUse"), ("beforeSubmitPrompt", "UserPromptSubmit")):
                events[native] = [g for g in events.get(native, []) if "GAG_DEV_TEAM" not in json.dumps(g)]
                events[native].append({"command": hook(event, harness)})
            put_json(".cursor/hooks.json", config)
            managed[".cursor/rules/gag-dev-team.mdc"] = (
                "---\ndescription: GAG Dev Team\nalwaysApply: true\n---\n"
                + guidance().replace(".agents/skills", ".cursor/skills") + "\n"
                "No picker principal, selecione o modelo equilibrado para o orquestrador. "
                "Os perfis de funções usam os modelos configurados; confira sua disponibilidade na conta.\n").encode()

        elif harness == "antigravity":
            mcp_json(".agents/mcp_config.json")
            config = json_file(".agents/hooks.json")
            config["gag-dev-team"] = {
                "SessionStart": [{"type": "command", "command": hook("SessionStart", harness), "timeout": 300}],
                "PreInvocation": [{"type": "command", "command": hook("UserPromptSubmit", harness), "timeout": 30}],
                "Stop": [{"type": "command", "command": hook("Stop", harness), "timeout": 120}],
                "PreToolUse": [{"matcher": "*", "hooks": [
                    {"type": "command", "command": hook("PreToolUse", harness), "timeout": 300}]}]
            }
            put_json(".agents/hooks.json", config)
            managed[".agents/rules/gag-dev-team.md"] = (
                "---\ntrigger: always_on\n---\n" + guidance() + "\n"
                "O perfil orquestrador é o principal; selecione-o quando o cliente solicitar um main agent. "
                "pro/flash são as rotas nativas disponíveis; o esforço no texto orienta a função, "
                "sem inventar campos de configuração não suportados.\n").encode()
    put_json(".gag-dev-team/models.json", role_map)
    return managed, merged
