#!/usr/bin/env python3
"""Consulta o Scripta sem gravar dados nem expor credenciais."""
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = "https://scripta-mcp.lecabe.com.br/mcp"
GUIDE = ROOT / "skills/development-workflow/references/scripta-access-guide.md"
LIMIT = 1024 * 1024


class CheckError(Exception):
    def __init__(self, kind):
        self.kind = kind


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, authorization):
        self.authorization = authorization
        self.session = None
        self.protocol = None
        self.counter = 0
        self.deadline = time.monotonic() + 24
        self.opener = urllib.request.build_opener(NoRedirect)

    def send(self, method, params=None, notification=False):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            self.counter += 1
            payload["id"] = self.counter
        headers = {
            "Authorization": self.authorization,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CheckError("network")
        request = urllib.request.Request(
            ENDPOINT, data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        try:
            with self.opener.open(request, timeout=min(6, remaining)) as response:
                self.session = response.headers.get("Mcp-Session-Id", self.session)
                if notification:
                    return None
                if "text/event-stream" in response.headers.get("Content-Type", ""):
                    message = self.read_event(response, payload["id"])
                else:
                    body = response.read(LIMIT + 1)
                    if len(body) > LIMIT:
                        raise CheckError("protocol")
                    message = json.loads(body)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                raise CheckError("auth") from None
            if error.code == 403:
                raise CheckError("permission") from None
            raise CheckError("network") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            raise CheckError("network") from None
        except (ValueError, UnicodeError):
            raise CheckError("protocol") from None
        if not isinstance(message, dict) or message.get("id") != payload["id"]:
            raise CheckError("protocol")
        if message.get("error") or "result" not in message:
            raise CheckError("tool")
        return message["result"]

    def read_event(self, response, expected_id):
        size = 0
        data = []
        while time.monotonic() < self.deadline:
            line = response.readline(LIMIT + 1)
            if not line:
                break
            size += len(line)
            if size > LIMIT:
                raise CheckError("protocol")
            line = line.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif not line and data:
                message = json.loads("\n".join(data))
                data = []
                if isinstance(message, dict) and message.get("id") == expected_id:
                    return message
        raise CheckError("protocol")

    def call(self, name, arguments):
        result = self.send("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict) or result.get("isError"):
            raise CheckError("tool")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        for block in result.get("content", []):
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text", "")
            # O Scripta pode incluir uma orientação antes do objeto JSON.
            for match in re.finditer(r"\{", text):
                try:
                    value, _ = json.JSONDecoder().raw_decode(text[match.start():])
                    if isinstance(value, dict):
                        return value
                except ValueError:
                    continue
        raise CheckError("protocol")


def inspect_access(root=ROOT, client_factory=Client):
    try:
        config = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
        server = config["mcpServers"]["docs"]
        if server["url"] != ENDPOINT or server["type"] != "streamable-http":
            return "config"
        authorization = server.get("headers", {}).get("Authorization", "").strip()
        token = authorization.removeprefix("Bearer ").strip()
        if not authorization.startswith("Bearer ") or not token or token == "ds_gere_um_token_acima":
            return "token"
        if "\n" in authorization or "\r" in authorization:
            return "config"
        client = client_factory(authorization)
        initialized = client.send("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "gag-dev-team-scripta-check", "version": "0.1.0"},
        })
        if not isinstance(initialized, dict) or not initialized.get("protocolVersion"):
            return "protocol"
        client.protocol = initialized["protocolVersion"]
        client.send("notifications/initialized", notification=True)
        projects = client.call("docs_list_projects", {})
        if not isinstance(projects.get("projects"), list):
            return "protocol"
        project = next(
            (p for p in projects["projects"] if isinstance(p, dict) and p.get("slug") == "renew-it"),
            None,
        )
        if project is None:
            return "project"
        if project.get("role") not in ("owner", "editor"):
            return "readonly"
        briefing = client.call("docs_briefing", {"project": "renew-it"})
        if briefing.get("project", {}).get("slug") != "renew-it":
            return "protocol"
        return "ok"
    except CheckError as error:
        return error.kind
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "config"


def guide_excerpt(sections):
    text = GUIDE.read_text(encoding="utf-8")
    blocks = re.split(r"(?=^## \d+\.)", text, flags=re.MULTILINE)
    return "\n".join(
        block.strip() for block in blocks
        if any(block.startswith(f"## {number}.") for number in sections)
    )


def output_for(status):
    notices = {
        "token": ("Scripta: falta configurar um token válido.", [2, 4]),
        "auth": ("Scripta: autenticação recusada (401). Confira ou renove a API Key.", [4, 7]),
        "permission": ("Scripta: operação recusada (403). Confira as permissões da conta e da integração.", [3, 6]),
        "project": ("Scripta acessível, mas renew-it não aparece. Solicite o compartilhamento ao responsável pela documentação.", [3, 5]),
        "readonly": ("Scripta: renew-it sem permissão de edição confirmada. Solicite acesso Editor ao responsável pela documentação.", [3, 6]),
        "network": ("Scripta: não foi possível concluir a conexão. Confira rede e disponibilidade; isso não prova ausência de conta.", [7]),
        "config": ("Scripta: configuração local inválida ou ausente.", [4, 5]),
        "protocol": ("Scripta: resposta incompatível; o acesso não pôde ser confirmado.", [7]),
        "tool": ("Scripta: uma ferramenta obrigatória falhou; confira permissões e disponibilidade.", [5, 7]),
    }
    workflow = ROOT / "skills/development-workflow/SKILL.md"
    if status == "ok":
        context = (
            "Consulta direta ao Scripta concluída: renew-it acessível e papel Editor/Owner informado. "
            "Isso não valida a conexão MCP do Codex nem prova permissão efetiva de escrita. "
            "Confira as ferramentas docs no cliente e consulte o briefing e as fontes antes de desenvolver. "
            f"Leia as regras obrigatórias em {workflow}."
        )
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    notice, sections = notices[status]
    try:
        excerpt = guide_excerpt(sections)
    except OSError:
        excerpt = f"Guia indisponível em {GUIDE}. Solicite ao responsável pelo Scripta a orientação de acesso."
    context = (
        f"{notice}\nNão inicie desenvolvimento dependente da documentação até regularizar o acesso. "
        "Ajude o usuário com o trecho do guia abaixo. Se não tiver conta, solicite uma ao responsável "
        "pelo Scripta; se faltar renew-it, solicite o compartilhamento ao responsável pela documentação.\n"
        f"Endpoint: {ENDPOINT}\n"
        "Configure a credencial apenas na cópia LOCAL INSTALADA do plugin, no cabeçalho Authorization "
        f"de {ROOT / 'mcp.json'}, como Bearer seguido do token pessoal. "
        "Não altere o pacote fonte com segredos, não peça tokens no chat nem os exiba. "
        "Reinicie o cliente após configurar. O placeholder não é uma credencial válida.\n"
        "Trecho do guia original; os exemplos usam sistema-financeiro: para este plugin, adapte para renew-it.\n\n"
        + excerpt
    )
    return {
        "systemMessage": notice,
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context},
    }


if __name__ == "__main__":
    try:
        print(json.dumps(output_for(inspect_access()), ensure_ascii=True))
    except Exception:
        # Nunca imprimir exceções: respostas e configurações podem conter segredos.
        print(json.dumps({"systemMessage": "Falha ao verificar Scripta. Consulte o guia de configuração.",
                          "hookSpecificOutput": {"hookEventName": "SessionStart",
                          "additionalContext": "Acesso ao Scripta não confirmado. Regularize antes de desenvolver."}}))
