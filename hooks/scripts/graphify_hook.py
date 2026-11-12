#!/usr/bin/env python3
"""Instalação e gate Graphify para aberturas de PR reconhecidas pelo plugin."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Documentação não é corpus: sua fonte de verdade continua sendo o Scripta.
CODE_EXTENSIONS = {
    ".py", ".php", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
    ".go", ".rs", ".java", ".kt", ".kts", ".scala", ".rb", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".swift", ".lua", ".sh", ".bash", ".ps1", ".psm1", ".sql", ".tf",
    ".html", ".css", ".scss", ".sass", ".less", ".json", ".yaml", ".yml", ".toml",
}
class GateError(Exception):
    pass


def run(args, cwd=None, timeout=30, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=timeout)
    if result.returncode:
        # Não repassar saídas externas: podem conter segredos do projeto.
        raise GateError("Comando de verificação falhou: " + Path(str(args[0])).name)
    return result.stdout


def ensure_graphify():
    for candidate in [shutil.which("graphify"), str(Path.home() / ".local/bin/graphify")]:
        if candidate and Path(candidate).is_file():
            run([candidate, "--version"], timeout=20)
            return candidate
    bash = shutil.which("bash")
    if not bash:
        raise GateError("Instalação exige Bash (Linux/WSL ou Git Bash), Python 3.10+ e acesso ao índice de pacotes.")
    output = run([bash, str(ROOT / "hooks/scripts/install-graphify.sh")], timeout=240)
    candidate = output.decode("utf-8").strip()
    if not candidate or not Path(candidate).is_file():
        raise GateError("Instalador não retornou um executável Graphify válido.")
    return candidate


def pr_request(event):
    name = event.get("tool_name", "")
    data = event.get("tool_input") or {}
    if not isinstance(data, dict):
        data = {"command": data} if isinstance(data, str) else {}
    if re.search(r"create_?pull_?request", name, re.I):
        if data.get("state") == "closed":
            return None
        repo = "/".join(str(data.get(k, "")) for k in ("owner", "repo"))
        return {"base": data.get("base"), "head": data.get("head"), "repo": repo,
                "cwd": event.get("cwd")}
    command = data.get("cmd", data.get("command", data.get("code", "")))
    if not isinstance(command, str):
        return None
    if not re.search(r"\bgh(?:\.exe)?\b[\s\S]*\bpr\s+create\b", command):
        # Tentativa reconhecível de usar a API por shell deve seguir o mesmo fluxo.
        if re.search(r"(gh\s+api|curl|requests\.post)[\s\S]*/pulls\b", command):
            raise GateError("Abra o PR com gh pr create em comando isolado para executar o gate Graphify.")
        return None
    # Não interpretar shell, scripts, cd ou comandos compostos como código executável.
    tokens = shlex.split(command)
    if not tokens or Path(tokens[0]).name.lower() not in ("gh", "gh.exe"):
        raise GateError("Execute gh pr create diretamente, em comando isolado, com workdir no worktree da feature.")
    if any(token in (";", "&&", "||", "|") for token in tokens):
        raise GateError("Separe a abertura de PR dos demais comandos e informe workdir explicitamente.")
    if "pr" not in tokens or tokens[tokens.index("pr") + 1:tokens.index("pr") + 2] != ["create"]:
        return None
    options = {}
    for index, token in enumerate(tokens):
        for long, short in [("--base", "-B"), ("--head", "-H"), ("--repo", "-R")]:
            if token in (long, short) and index + 1 < len(tokens):
                options[long] = tokens[index + 1]
            elif token.startswith(long + "="):
                options[long] = token.split("=", 1)[1]
    return {"base": options.get("--base"), "head": options.get("--head"),
            "repo": options.get("--repo"), "cwd": data.get("workdir") or event.get("cwd")}


def repository_slug(remote):
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote.strip())
    return "/".join(match.groups()).lower() if match else None


def analyze_pr(request, binary):
    cwd = request.get("cwd")
    if not cwd:
        raise GateError("Não foi possível identificar o worktree do PR.")
    root = Path(run(["git", "rev-parse", "--show-toplevel"], cwd=cwd).decode().strip())
    base = request.get("base")
    if base not in ("stage", "prod"):
        raise GateError("Informe explicitamente o destino stage ou prod na abertura do PR.")
    branch = run(["git", "branch", "--show-current"], cwd=root).decode().strip()
    head = request.get("head") or branch
    if not branch or branch in ("stage", "prod") or head != branch:
        raise GateError("O head do PR deve ser a branch da feature aberta neste worktree.")
    head_commit = run(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    remote = run(["git", "remote", "get-url", "origin"], cwd=root).decode().strip()
    slug = repository_slug(remote)
    requested_repo = request.get("repo")
    if not slug or (requested_repo and requested_repo.lower().removeprefix("https://github.com/").rstrip("/") != slug):
        raise GateError("O repositório do PR não corresponde ao remoto origin deste worktree.")
    if run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root).strip():
        raise GateError("O worktree precisa estar limpo e commitado antes do PR; não serão indexadas mudanças fora do PR.")
    run(["git", "fetch", "origin", base], cwd=root, timeout=60)
    base_ref = "refs/remotes/origin/" + base
    base_commit = run(["git", "rev-parse", "--verify", base_ref], cwd=root).decode().strip()
    published = run(["git", "ls-remote", "--heads", "origin", "refs/heads/" + branch], cwd=root, timeout=60).decode().split()
    if not published or published[0] != head_commit:
        raise GateError("Publique a branch da feature antes do PR; o head remoto deve coincidir com o commit local.")
    changed = run(["git", "diff", "--name-only", "-z", "--no-renames", base_commit + "..." + head_commit, "--"], cwd=root)
    files = [os.fsdecode(p) for p in changed.split(b"\0") if p]
    if not files:
        raise GateError("Nenhum arquivo alterado em relação ao destino; não há escopo para analisar.")
    code, removed, skipped = [], [], []
    # Ler o commit, não arquivos de trabalho; impede seguir symlinks ou exportar segredos.
    tree = run(["git", "ls-tree", "-r", "-z", head_commit], cwd=root)
    modes = {}
    for entry in tree.split(b"\0"):
        if entry:
            metadata, path = entry.split(b"\t", 1)
            modes[os.fsdecode(path)] = metadata.split(b" ", 1)[0]
    with tempfile.TemporaryDirectory(prefix="gag-graphify-pr-") as temp:
        corpus = Path(temp) / "corpus"
        corpus.mkdir()
        extraction_output = Path(temp) / "result"
        for relative in files:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise GateError("Caminho inválido no diff do PR.")
            if relative not in modes:
                removed.append(relative)
                continue
            sensitive = path.name.lower().startswith(".env") or any(
                part.lower() in ("secrets", "credentials", ".git") for part in path.parts
            )
            if sensitive or path.suffix.lower() not in CODE_EXTENSIONS or modes[relative] not in (b"100644", b"100755"):
                skipped.append(relative)
                continue
            contents = run(["git", "show", head_commit + ":" + relative], cwd=root)
            if b"\0" in contents:
                skipped.append(relative)
                continue
            target = corpus / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
            code.append(relative)
        output = root / "graphify-out" / "pr-check" / base
        output.mkdir(parents=True, exist_ok=True)
        if code:
            env = dict(os.environ)
            env.pop("GRAPHIFY_OUT", None)
            # Sem LLM, sem credencial e sem publicação em Graphify Cloud.
            run([binary, "extract", str(corpus), "--code-only", "--no-cluster",
                 "--out", str(extraction_output)], cwd=root, timeout=180, env=env)
            generated_graph = extraction_output / "graphify-out" / "graph.json"
            if not generated_graph.is_file():
                raise GateError("Graphify não gerou o grafo dos arquivos alterados.")
            graph = json.loads(generated_graph.read_text(encoding="utf-8"))
            if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
                raise GateError("Grafo retornado pelo Graphify é inválido.")
            graph_file = output / "graph.json"
            # Troca somente prefixos de origem: os arquivos do corpus temporário
            # correspondem exatamente aos caminhos relativos do commit.
            def normalize(value):
                if isinstance(value, str) and value.startswith(str(corpus) + os.sep):
                    return value[len(str(corpus)) + 1:]
                if isinstance(value, list):
                    return [normalize(v) for v in value]
                if isinstance(value, dict):
                    return {k: normalize(v) for k, v in value.items()}
                return value
            graph_file.write_text(json.dumps(normalize(graph), ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            (output / "graph.json").unlink(missing_ok=True)
            graph_file = None
        record = {
            "head": head_commit,
            "base": base, "base_commit": base_commit,
            "analyzed": code, "removed": removed, "skipped": skipped,
            "graph": str(graph_file) if graph_file else None,
        }
        (output / "check.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    if run(["git", "rev-parse", "HEAD"], cwd=root).decode().strip() != head_commit:
        raise GateError("O commit mudou durante a análise. Repita antes de abrir o PR.")
    if run(["git", "branch", "--show-current"], cwd=root).decode().strip() != branch:
        raise GateError("A branch mudou durante a análise. Repita antes de abrir o PR.")
    if run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root).strip():
        raise GateError("graphify-out/ precisa estar ignorado pelo Git antes de abrir o PR.")
    return f"Graphify pré-PR concluído: {len(code)} arquivo(s) de código, {len(removed)} remoção(ões), {len(skipped)} fora da indexação. Registro local: {output / 'check.json'}."


def respond(event_name, message, deny=False):
    result = {"hookEventName": event_name}
    if deny:
        result.update(permissionDecision="deny", permissionDecisionReason=message)
    else:
        result["additionalContext"] = message
    return {"hookSpecificOutput": result}


def main():
    mode = sys.argv[1]
    event = json.load(sys.stdin)
    if mode == "session":
        try:
            binary = ensure_graphify()
            message = (
                f"Graphify disponível: {binary}. Para localizar código e relações, use graphify query/path/explain. "
                "Documentação e regras do sistema devem ser pesquisadas no Scripta/renew-it. "
                "Antes de PRs use gh pr create isolado, com base stage ou prod e workdir no worktree da feature. "
                "O hook analisará o diff commitado; mantenha graphify-out/ ignorado pelo Git."
            )
        except (GateError, OSError, subprocess.TimeoutExpired) as error:
            message = "Graphify não ficou disponível. Regularize antes de localizar código ou abrir PRs. " + str(error)
        print(json.dumps(respond("SessionStart", message), ensure_ascii=True))
        return
    try:
        request = pr_request(event)
        if request is None:
            print("{}")
            return
        message = analyze_pr(request, ensure_graphify())
        print(json.dumps(respond("PreToolUse", message), ensure_ascii=True))
    except (GateError, OSError, ValueError, subprocess.TimeoutExpired):
        print(json.dumps(respond(
            "PreToolUse",
            "PR bloqueado: a verificação Graphify não foi concluída. Confirme instalação, worktree limpo, "
            "origin correto, branch publicada com o mesmo commit local, destino explícito stage/prod e graphify-out/ ignorado. "
            "Execute a abertura com gh pr create isolado e workdir no worktree; não contorne o gate.",
            deny=True), ensure_ascii=True))


if __name__ == "__main__":
    main()
