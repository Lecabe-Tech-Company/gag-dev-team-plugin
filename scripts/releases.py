"""Releases estáveis do próprio repositório; sem fallback silencioso para branches."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

REPOSITORY = "Lecabe-Tech-Company/gag-dev-team-plugin"
LATEST = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest"
ASSET_PREFIX = "https://github.com/" + REPOSITORY + "/releases/download/"
MAX_PACKAGE = 50 * 1024 * 1024


def fetch_bytes(url, limit=MAX_PACKAGE):
    request = urllib.request.Request(url, headers={"User-Agent": "GAG-Dev-Team", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Artefato de release excede o limite.")
    return content


def fetch_json(url):
    return json.loads(fetch_bytes(url, 1024 * 1024))


def version(tag):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", str(tag))
    if not match:
        raise ValueError("A release deve usar uma versão estável vX.Y.Z.")
    return tuple(map(int, match.groups()))


def latest_release(fetch_json=fetch_json):
    release = fetch_json(LATEST)
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("A instalação exige uma release publicada estável.")
    version(release.get("tag_name"))
    return release


def extract_release(release, destination, fetch_bytes=fetch_bytes):
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("Release não estável.")
    tag = release.get("tag_name")
    version(tag)
    filename = "gag-dev-team-plugin-" + tag + ".zip"
    assets = {a.get("name"): a.get("browser_download_url", "") for a in release.get("assets", [])}
    for name in (filename, "SHA256SUMS"):
        if not assets.get(name, "").startswith(ASSET_PREFIX):
            raise ValueError("Artefato de release ausente ou fora do repositório oficial.")
    checksum = fetch_bytes(assets["SHA256SUMS"]).decode("ascii")
    expected = next((line.split()[0] for line in checksum.splitlines()
                     if len(line.split()) == 2 and line.split()[1].lstrip("*") == filename), None)
    archive = fetch_bytes(assets[filename])
    if not expected or hashlib.sha256(archive).hexdigest() != expected.lower():
        raise ValueError("Checksum do pacote não confere; instalação preservada.")
    destination = Path(destination)
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        entries = package.infolist()
        if len(entries) > 5000 or sum(i.file_size for i in entries) > MAX_PACKAGE:
            raise ValueError("Pacote muito grande.")
        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or "\\" in name
                    or PureWindowsPath(name).drive or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Caminho inseguro no pacote.")
        package.extractall(destination)
    if not (destination / "plugin.json").is_file() or not (destination / "scripts/project_install.py").is_file():
        raise ValueError("Pacote incompleto.")
    return destination


def apply_release(project, source, harnesses, tag):
    # O instalador novo também é parte da release. Não gerar configurações com código antigo.
    code = ("import json,sys;from pathlib import Path;"
            "sys.path.insert(0,str(Path(sys.argv[2])/'scripts'));"
            "from project_install import install;"
            "result=install(sys.argv[1],source=Path(sys.argv[2]),"
            "harnesses=json.loads(sys.argv[3]),release_tag=sys.argv[4]);"
            "print(json.dumps(str(result)))")
    result = subprocess.run(
        [sys.executable, "-c", code, str(project), str(source), json.dumps(harnesses), tag],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        raise ValueError("A release não pôde ser aplicada. A configuração anterior foi preservada; confira possíveis personalizações.")
    return Path(json.loads(result.stdout.strip()))


def install_latest(project, harnesses=None, fetch_json=fetch_json, fetch_bytes=fetch_bytes):
    from project_install import install
    release = latest_release(fetch_json)
    with tempfile.TemporaryDirectory(prefix="gag-release-") as temp:
        source = extract_release(release, temp, fetch_bytes)
        return apply_release(project, source, harnesses, release["tag_name"])


def update_project(project, fetch_json=fetch_json, fetch_bytes=fetch_bytes):
    from project_install import install, project_root, safe_path
    project = project_root(project)
    state_path = safe_path(project, ".gag-dev-team/install.json")
    if not state_path.is_file():
        return {"updated": False, "reason": "not-installed"}
    lock = safe_path(project, ".gag-dev-team/update.lock")
    if lock.exists() and time.time() - lock.stat().st_mtime > 600:
        lock.unlink()
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return {"updated": False, "reason": "in-progress"}
    try:
        os.close(descriptor)
        state = json.loads(state_path.read_text())
        release = latest_release(fetch_json)
        if state.get("release_tag") and version(release["tag_name"]) <= version(state["release_tag"]):
            return {"updated": False, "version": state["release_tag"]}
        with tempfile.TemporaryDirectory(prefix="gag-update-") as temp:
            source = extract_release(release, temp, fetch_bytes)
            apply_release(project, source, state.get("harnesses", ["codex"]), release["tag_name"])
        return {"updated": True, "version": release["tag_name"]}
    finally:
        lock.unlink(missing_ok=True)
