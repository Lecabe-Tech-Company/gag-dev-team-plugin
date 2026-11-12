"""Empacota uma release estável sem modificar os arquivos fonte."""
import argparse
import hashlib
import json
import urllib.error
import zipfile
from pathlib import Path

from releases import latest_release, version


def next_tag(current, latest=None):
    candidate = version(current)
    if latest is None or candidate > version(latest):
        return "v" + ".".join(map(str, candidate))
    major, minor, patch = version(latest)
    return f"v{major}.{minor}.{patch + 1}"


def build_release(root, destination, tag):
    root, destination = Path(root), Path(destination)
    version(tag)
    destination.mkdir(parents=True, exist_ok=True)
    artifact = destination / ("gag-dev-team-plugin-" + tag + ".zip")
    files = []
    for directory in ("agents", "skills", "hooks", "scripts", "ui", "mcp", "bin"):
        files.extend(p for p in (root / directory).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and p.name != ".gitkeep")
    files.extend(root / name for name in ("package.json", "plugin.json", "mcp.json", "README.md"))
    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in sorted(files):
            contents = path.read_bytes()
            if path.name in ("package.json", "plugin.json") and path.parent == root:
                metadata = json.loads(contents)
                metadata["version"] = tag.removeprefix("v")
                contents = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode()
            package.writestr(path.relative_to(root).as_posix(), contents)
    checksum = destination / "SHA256SUMS"
    checksum.write_text(hashlib.sha256(artifact.read_bytes()).hexdigest() + "  " + artifact.name + "\n")
    return artifact, checksum


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="dist")
    parser.add_argument("--tag")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tag = args.tag
    if tag is None:
        try:
            latest = latest_release()["tag_name"]
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            latest = None
        tag = next_tag(json.loads((root / "package.json").read_text())["version"], latest)
    artifact, checksum = build_release(root, args.output, tag)
    print(json.dumps({"tag": tag, "artifact": str(artifact), "checksum": str(checksum)}))


if __name__ == "__main__":
    main()
