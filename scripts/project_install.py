"""Instala componentes nativos do Codex por projeto, sem gravar segredos no TOML."""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "# BEGIN GAG DEV TEAM"
END = "# END GAG DEV TEAM"
AGENT_BEGIN = "<!-- BEGIN GAG DEV TEAM -->"
AGENT_END = "<!-- END GAG DEV TEAM -->"
ENDPOINT = "https://scripta-mcp.lecabe.com.br/mcp"


def project_root(project):
    project = Path(project).resolve(strict=True)
    if not project.is_dir():
        raise ValueError("Escolha uma pasta de projeto existente.")
    return project


def safe_path(project, relative):
    target = project / relative
    if not target.resolve().is_relative_to(project) or target.is_symlink():
        raise ValueError("O caminho de instalação não pode ser um link para outro local.")
    return target


def read(path, default=""):
    return path.read_text(encoding="utf-8") if path.exists() else default


def block(text, start, end, replacement):
    if text.count(start) != text.count(end) or text.count(start) > 1:
        raise ValueError("Bloco GAG existente inválido; preserve e revise a configuração.")
    if start in text:
        before, rest = text.split(start, 1)
        _, after = rest.split(end, 1)
        return before + replacement + after
    return text.rstrip() + ("\n\n" if text.strip() else "") + replacement + "\n"


def atomic_write(path, contents, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".gag-write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
        if private:
            os.chmod(temp_name, 0o600)
        elif path.exists():
            os.chmod(temp_name, path.stat().st_mode & 0o777)
        else:
            os.chmod(temp_name, 0o644)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def ignore_private_data(project):
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", ".gag-dev-team"],
        cwd=project, capture_output=True, check=True,
    )
    if tracked.stdout:
        raise ValueError(".gag-dev-team já contém arquivos versionados; remova-os do índice antes de instalar.")
    result = subprocess.run(["git", "rev-parse", "--git-path", "info/exclude"],
                            cwd=project, capture_output=True, text=True, check=True)
    exclude = Path(result.stdout.strip())
    if not exclude.is_absolute():
        exclude = project / exclude
    text = read(exclude)
    if "/.gag-dev-team/" not in text.splitlines():
        atomic_write(exclude, (text.rstrip() + "\n/.gag-dev-team/\n").encode())


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


def install(project, source=ROOT, harnesses=None, release_tag=None):
    project = project_root(project)
    source = Path(source).resolve()
    private = safe_path(project, ".gag-dev-team")
    runtime = safe_path(project, ".gag-dev-team/plugin")
    state_path = safe_path(project, ".gag-dev-team/install.json")
    state = json.loads(read(state_path, "{}"))
    previous = state.get("files", {})
    from harness_adapters import HARNESS_NAMES, build
    selected = list(dict.fromkeys(harnesses if harnesses is not None else state.get("harnesses", ["codex"])))
    if not selected or any(h not in HARNESS_NAMES for h in selected):
        raise ValueError("Selecione ao menos um ambiente suportado: codex, claude, cursor, antigravity.")
    writes = {}

    def managed(relative, contents):
        target = safe_path(project, relative)
        if target.exists():
            current = target.read_bytes()
            if current != contents and previous.get(relative) != digest(current):
                raise ValueError(f"Arquivo personalizado preservado: {relative}")
        writes[target] = contents

    # Runtime privado contém apenas os componentes distribuídos, sem cache ou testes.
    for directory in ("agents", "skills", "hooks", "scripts", "ui", "mcp", "bin"):
        for path in sorted((source / directory).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.name == ".gitkeep":
                continue
            relative = path.relative_to(source).as_posix()
            managed(".gag-dev-team/plugin/" + relative, path.read_bytes())
    for filename in ("plugin.json", "mcp.json"):
        managed(".gag-dev-team/plugin/" + filename, (source / filename).read_bytes())
    profiles = sorted((source / "agents").glob("gag-*.toml"))
    if len(profiles) != 5:
        raise ValueError("Pacote incompleto: faltam os cinco perfis do time.")
    for path in profiles:
        tomllib.loads(path.read_text(encoding="utf-8"))
    for path in sorted((source / "skills").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.name != ".gitkeep":
            managed(".agents/skills/" + path.relative_to(source / "skills").as_posix(), path.read_bytes())

    native_files, merged_files = build(project, runtime, source, selected)
    for relative, contents in native_files.items():
        managed(relative, contents)
    managed_paths = set(writes)
    for relative, contents in merged_files.items():
        writes[safe_path(project, relative)] = contents
    # Preflight completo; rollback restaura o estado anterior se alguma escrita falhar.
    ignore_private_data(project)
    before = {path: path.read_bytes() if path.exists() else None for path in writes}
    previous_state = state_path.read_bytes() if state_path.exists() else None
    try:
        for path, contents in writes.items():
            if not path.exists() or path.read_bytes() != contents:
                atomic_write(path, contents)
        file_hashes = {
            path.relative_to(project).as_posix(): digest(contents)
            for path, contents in writes.items() if path in managed_paths
        }
        state.update(version=2, files=file_hashes, harnesses=selected)
        if release_tag is not None:
            state["release_tag"] = release_tag
        atomic_write(state_path, (json.dumps(state, indent=2) + "\n").encode())
    except Exception:
        for path, contents in before.items():
            if contents is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, contents)
        if previous_state is None:
            state_path.unlink(missing_ok=True)
        else:
            atomic_write(state_path, previous_state)
        raise
    return runtime

def configure_scripta(project, token):
    project = project_root(project)
    if not isinstance(token, str):
        raise ValueError("Informe uma chave de acesso.")
    if len(token) > 4096 or any(c in token for c in ("\r", "\n", "\0")):
        raise ValueError("Informe uma chave válida, sem quebras de linha, de até 4096 caracteres.")
    token = token.strip()
    if not token:
        raise ValueError("Informe uma chave válida, sem quebras de linha, de até 4096 caracteres.")
    if token == "ds_gere_um_token_acima":
        raise ValueError("Substitua o exemplo pela sua chave pessoal do Scripta.")
    if not safe_path(project, ".gag-dev-team/install.json").is_file():
        raise ValueError("Instale o GAG Dev Team neste projeto antes de configurar.")
    # Reinstalação idempotente também confere se a configuração nativa foi preservada.
    runtime = install(project, source=project / ".gag-dev-team/plugin")
    token_path = safe_path(project, ".gag-dev-team/scripta-token")
    ignore_private_data(project)
    atomic_write(token_path, token.encode(), private=True)
    return runtime


def install_graphify(runtime):
    if os.name == "nt":
        # A mesma distribuição Python já é pré-requisito da CLI.
        binary = shutil.which("graphify")
        if not binary:
            environment = Path(runtime).parent / "tools/graphify"
            python = environment / "Scripts/python.exe"
            candidate = environment / "Scripts/graphify.exe"
            if not candidate.is_file():
                subprocess.run([sys.executable, "-m", "venv", str(environment)], capture_output=True, check=True, timeout=60)
                subprocess.run([str(python), "-m", "pip", "install", "graphifyy"], capture_output=True, check=True, timeout=240)
            binary = str(candidate)
        if not binary:
            raise RuntimeError("Confira Graphify no PATH e tente novamente.")
        subprocess.run([binary, "--version"], capture_output=True, check=True, timeout=20)
        return binary
    result = subprocess.run(["bash", str(Path(runtime) / "hooks/scripts/install-graphify.sh")],
                            capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise RuntimeError("Não foi possível instalar Graphify. Confira Python, uv/pipx e a rede e tente novamente.")
    return result.stdout.strip()
