#!/usr/bin/env python3
"""CLI local: install e configure, sem serviços ou dependências web externas."""
import argparse
import json
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from project_install import ROOT, configure_scripta, install, install_graphify, project_root


def create_server(project, graphify_installer=None):
    project = project_root(project)
    if not (project / ".gag-dev-team/install.json").is_file():
        raise ValueError("Execute install neste projeto antes de configure.")
    runner = graphify_installer or install_graphify

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Nunca registrar o corpo que contém a chave.

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def send(self, status, payload, content_type="application/json"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def authorized(self, writing=False):
            address = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != address:
                return False
            prefix = "/" + self.server.session + "/"
            if not self.path.startswith(prefix):
                return False
            if writing and (self.headers.get("Origin") != "http://" + address
                            or self.headers.get("X-GAG-Session") != self.server.session):
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                self.send(403, {"error": "Sessão de configuração inválida."})
                return
            route = self.path[len(self.server.session) + 2:]
            if route == "api/status":
                with self.server.state_lock:
                    self.send(200, dict(self.server.state))
                return
            assets = {"": ("index.html", "text/html; charset=utf-8"),
                      "configure.js": ("configure.js", "text/javascript; charset=utf-8"),
                      "configure.css": ("configure.css", "text/css; charset=utf-8"),
                      "brand/scripta-logo-h.png": ("brand/scripta-logo-h.png", "image/png"),
                      "brand/scripta-logo-h-dark.png": ("brand/scripta-logo-h-dark.png", "image/png"),
                      "brand/scripta-icon.png": ("brand/scripta-icon.png", "image/png")}
            if route not in assets:
                self.send(404, {"error": "Página não encontrada."})
                return
            name, content_type = assets[route]
            self.send(200, (ROOT / "ui" / name).read_bytes(), content_type)

        def do_POST(self):
            if not self.authorized(writing=True):
                self.send(403, {"error": "Reabra configure para obter uma sessão válida."})
                return
            if self.path != "/" + self.server.session + "/api/save":
                self.send(404, {"error": "Ação não encontrada."})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                self.send(415, {"error": "Envie a chave pelo formulário."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 8192:
                    self.send(413, {"error": "Conteúdo inválido ou muito grande."})
                    return
                payload = json.loads(self.rfile.read(length))
                token = payload.get("token") if isinstance(payload, dict) else None
            except (ValueError, UnicodeError, TimeoutError):
                self.send(400, {"error": "Não foi possível ler a chave. Tente novamente."})
                return
            with self.server.state_lock:
                if self.server.state["status"] in ("saving", "installing", "done"):
                    self.send(409, {"error": "Uma configuração já está em andamento ou foi concluída."})
                    return
                try:
                    runtime = configure_scripta(project, token)
                except (OSError, ValueError, RuntimeError):
                    self.send(400, {"error": "Confira sua chave do Scripta (até 4096 caracteres, sem quebras de linha) e tente novamente."})
                    return
                self.server.state.update(status="installing", message="Chave salva. Finalizando a conexão com o Scripta…")
            self.send(202, {"status": "installing", "message": "Chave salva. Finalizando a conexão com o Scripta…"})
            def finish():
                try:
                    runner(runtime)
                    status = "done"
                    message = "Sua chave do Scripta foi salva com segurança. Você já pode fechar esta janela."
                except Exception:
                    status = "error"
                    message = "Sua chave do Scripta foi salva. Não foi possível concluir a preparação da conexão. Confira o terminal e tente novamente."
                with self.server.state_lock:
                    self.server.state.update(status=status, message=message)
            threading.Thread(target=finish, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.session = secrets.token_urlsafe(32)
    server.state_lock = threading.Lock()
    server.state = {"status": "idle", "message": "Informe sua chave e clique em Salvar."}
    return server


def choose_harnesses(project, requested):
    from harness_adapters import HARNESS_NAMES
    if requested:
        selected = [h.strip().lower() for item in requested for h in item.split(",") if h.strip()]
    else:
        state_path = Path(project).resolve() / ".gag-dev-team/install.json"
        if state_path.exists():
            return json.loads(state_path.read_text()).get("harnesses", ["codex"])
        if not sys.stdin.isatty():
            raise ValueError("Selecione os ambientes com --harness codex,claude,cursor,antigravity.")
        print("Onde você quer instalar seu time? Escolha um ou mais ambientes:")
        keys = list(HARNESS_NAMES)
        for number, key in enumerate(keys, 1):
            print(f"  [ ] {number}. {HARNESS_NAMES[key]}")
        answer = input("Números ou nomes, separados por vírgula (ex.: 1,2): ").strip()
        selected = []
        for item in answer.replace(" ", ",").split(","):
            if item:
                selected.append(keys[int(item)-1] if item.isdigit() and 1 <= int(item) <= len(keys) else item.lower())
    if not selected or any(h not in HARNESS_NAMES for h in selected):
        raise ValueError("Escolha ao menos um ambiente válido: codex, claude, cursor, antigravity.")
    return list(dict.fromkeys(selected))


def main(argv=None):
    from releases import install_latest, update_project
    from sdd_gate import declare_sdd, approve_sdd, record_sdd_approval
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "rules":
        return run_user_rules_cli(arguments[1:])
    if arguments and arguments[0] == "skills":
        return run_user_skills_cli(arguments[1:])
    parser = argparse.ArgumentParser(description="GAG Dev Team: seu time de desenvolvimento, organizado.")
    parser.add_argument("command", choices=["install", "configure", "update", "declare-sdd", "approve-sdd"])
    parser.add_argument("--project", default=".", help="Pasta do projeto")
    parser.add_argument("--harness", action="append", help="Ambientes separados por vírgula; sem opção, mostra seleção inicial")
    parser.add_argument("--reference", help="Código ou slug do SDD no Scripta")
    parser.add_argument("--sdd-version", help="Número da versão vigente do SDD")
    parser.add_argument("--confirm", action="store_true", help="Confirmação sim/não feita diretamente por uma pessoa no terminal")
    parser.add_argument("--evidence", help="Trecho literal do aceite já dado pelo usuário na conversa")
    parser.add_argument("--recorded-by", help="Pessoa ou agente que registrou a evidência contextual")
    parser.add_argument("--no-browser", action="store_true", help="Apenas informar a URL local")
    args = parser.parse_args(arguments)
    try:
        if args.command == "install":
            selected = choose_harnesses(args.project, args.harness)
            runtime = install_latest(args.project, harnesses=selected)
            print(f"Seu time está instalado em {runtime.parent.parent}.")
            print("Agora execute: npx --yes github:Lecabe-Tech-Company/gag-dev-team-plugin configure")
            print("Reabra seu ambiente e revise as permissões solicitadas. O orquestrador será seu interlocutor.")
            return
        if args.command == "update":
            result = update_project(args.project)
            if result.get("reason") == "not-installed":
                raise ValueError("Plugin ainda não instalado. Execute install primeiro.")
            print("Plugin atualizado para " + result["version"] if result.get("updated") else "Seu plugin já está atualizado ou há uma atualização em andamento.")
            return
        if args.command == "declare-sdd":
            state = declare_sdd(args.project, args.reference, args.sdd_version)
            print(f"SDD declarado: {state['reference']} v{state['version']}. O orquestrador avalia o aceite no contexto da conversa.")
            return
        if args.command == "approve-sdd":
            if args.evidence is not None or args.recorded_by is not None:
                if args.evidence is None or args.recorded_by is None:
                    raise ValueError("Use --evidence e --recorded-by juntos para registrar o aceite contextual.")
                state = record_sdd_approval(args.project, args.reference, args.sdd_version,
                                            args.evidence, args.recorded_by)
                print(f"Evidência contextual registrada para SDD {state['reference']} v{state['version']}.")
                return

            explicit = args.confirm
            if not explicit and sys.stdin.isatty():
                answer = input(f"A pessoa usuária confirmou o SDD {args.reference} v{args.sdd_version}? [s/N] ").strip().casefold()
                explicit = answer in ("s", "sim", "y", "yes")
            state = approve_sdd(args.project, args.reference, args.sdd_version, explicit=explicit)
            print(f"Confirmação terminal registrada para SDD {state['reference']} v{state['version']}.")
            return
        server = create_server(args.project)
        url = f"http://127.0.0.1:{server.server_port}/{server.session}/"
        print("Abra a conexão do Scripta:", url, flush=True)
        print("Mantenha este terminal aberto. Ctrl+C encerra a janela.", flush=True)
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except webbrowser.Error:
                pass
        expiry = threading.Timer(900, server.shutdown)
        expiry.daemon = True
        expiry.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            expiry.cancel()
            server.server_close()
    except subprocess.CalledProcessError:
        parser.exit(1, "Instalação não concluída. Execute em um projeto Git válido e confira suas permissões.\n")
    except (OSError, ValueError, RuntimeError) as error:
        if args.command in ("declare-sdd", "approve-sdd"):
            parser.exit(1, f"Registro local não concluído: {error}. O estado local não decide se a conversa autorizou; use o contexto real sem repetir aceite claro por causa desta falha.\n")
        parser.exit(1, f"Configuração não concluída: {error}\n")


def run_user_rules_cli(argv):
    import json
    from user_rules import (
        UserRulesError,
        context_for,
        list_rules,
        policy_snapshot,
        propose_rule,
        read_rule,
        remove_rule,
        review_rule,
        storage_root,
    )

    parser = argparse.ArgumentParser(prog="gag-dev-team rules", description="Manage private declarative project rules.")
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("policy", "list", "add", "context"):
        command = commands.add_parser(name)
        command.add_argument("--project", default=".", help="Git project or linked worktree path")
    show_parser = commands.add_parser("show")
    show_parser.add_argument("rule_id")
    show_parser.add_argument("--project", default=".")
    review_parser = commands.add_parser("review")
    review_parser.add_argument("rule_id")
    review_parser.add_argument("--project", default=".")
    review_parser.add_argument("--decision", choices=("accept", "reject", "unclear"), required=True)
    review_parser.add_argument("--reviewer", required=True)
    review_parser.add_argument("--reason", required=True)
    review_parser.add_argument("--content-digest", required=True)
    review_parser.add_argument("--policy-digest", required=True)
    review_parser.add_argument("--expected-revision", type=int, required=True)
    remove_parser = commands.add_parser("remove")
    remove_parser.add_argument("rule_id")
    remove_parser.add_argument("--project", default=".")
    remove_parser.add_argument("--expected-revision", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "policy":
            storage_root(args.project)
            result = policy_snapshot()
        elif args.action == "list":
            result = list_rules(args.project)
        elif args.action == "add":
            if sys.stdin.isatty():
                raise UserRulesError("Provide the proposed rule through standard input, not a command argument.")
            try:
                content = sys.stdin.buffer.read().decode("utf-8")
            except UnicodeError as error:
                raise UserRulesError("The proposed rule must be valid UTF-8 text.") from error
            result = propose_rule(args.project, content)
        elif args.action == "show":
            result = read_rule(args.project, args.rule_id)
        elif args.action == "review":
            result = review_rule(
                args.project,
                args.rule_id,
                args.decision,
                args.reviewer,
                args.reason,
                args.content_digest,
                args.policy_digest,
                args.expected_revision,
            )
        elif args.action == "remove":
            result = remove_rule(args.project, args.rule_id, args.expected_revision)
        else:
            result = context_for(args.project)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    except (UserRulesError, OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"User rules operation failed: {error}\n")


def run_user_skills_cli(argv):
    import json
    from user_skills import (
        UserSkillsError,
        catalog_for,
        confirm_skill_origin,
        list_skills,
        load_skill,
        propose_skill,
        read_skill,
        remove_skill,
        review_skill,
        storage_root,
    )
    from user_rules import policy_snapshot

    parser = argparse.ArgumentParser(prog="gag-dev-team skills", description="Manage private user skills.")
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("policy", "list", "add", "catalog"):
        command = commands.add_parser(name)
        command.add_argument("--project", default=".")
    for name in ("show", "load"):
        command = commands.add_parser(name)
        command.add_argument("skill_id")
        command.add_argument("--project", default=".")
    review_parser = commands.add_parser("review")
    review_parser.add_argument("skill_id")
    review_parser.add_argument("--project", default=".")
    review_parser.add_argument("--decision", choices=("accept", "reject", "unclear"), required=True)
    review_parser.add_argument("--reviewer", required=True)
    review_parser.add_argument("--reason", required=True)
    review_parser.add_argument("--content-digest", required=True)
    review_parser.add_argument("--policy-digest", required=True)
    review_parser.add_argument("--expected-revision", type=int, required=True)
    confirm_parser = commands.add_parser("confirm")
    confirm_parser.add_argument("skill_id")
    confirm_parser.add_argument("--project", default=".")
    confirm_parser.add_argument("--content-digest", required=True)
    confirm_parser.add_argument("--policy-digest", required=True)
    confirm_parser.add_argument("--expected-revision", type=int, required=True)
    remove_parser = commands.add_parser("remove")
    remove_parser.add_argument("skill_id")
    remove_parser.add_argument("--project", default=".")
    remove_parser.add_argument("--expected-revision", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "policy":
            storage_root(args.project)
            result = policy_snapshot()
        elif args.action == "list":
            result = list_skills(args.project)
        elif args.action == "add":
            if sys.stdin.isatty():
                raise UserSkillsError("Provide the proposed skill as JSON through standard input.")
            try:
                bundle = json.loads(sys.stdin.buffer.read().decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise UserSkillsError("The proposed skill must be valid UTF-8 JSON.") from error
            result = propose_skill(args.project, bundle)
        elif args.action == "show":
            result = read_skill(args.project, args.skill_id)
        elif args.action == "review":
            result = review_skill(args.project, args.skill_id, args.decision, args.reviewer, args.reason,
                                 args.content_digest, args.policy_digest, args.expected_revision)
        elif args.action == "confirm":
            if sys.stdin.isatty():
                raise UserSkillsError("Provide the user's clarification through standard input, not command arguments.")
            try:
                confirmation = sys.stdin.buffer.read().decode("utf-8")
            except UnicodeError as error:
                raise UserSkillsError("The user's clarification must be valid UTF-8 text.") from error
            result = confirm_skill_origin(args.project, args.skill_id, confirmation,
                                          args.content_digest, args.policy_digest, args.expected_revision)
        elif args.action == "remove":
            result = remove_skill(args.project, args.skill_id, args.expected_revision)
        elif args.action == "catalog":
            result = catalog_for(args.project)
        else:
            result = load_skill(args.project, args.skill_id)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return
    except (UserSkillsError, OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"User skills operation failed: {error}\n")


if __name__ == "__main__":
    main()
