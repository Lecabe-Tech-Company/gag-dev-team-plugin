"""Install reviewed personal extensions without versioning personal content."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from event_store import append_event
from user_rules import policy_snapshot, private_directory, private_lock

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024


class PersonalExtensionError(RuntimeError):
    """A personal extension cannot be installed safely or verified."""


def _private_tree(directory: Path):
    missing = []
    current = directory
    while not current.exists():
        if current.is_symlink():
            raise PersonalExtensionError("Personal extension storage contains a symbolic link.")
        missing.append(current)
        current = current.parent
    if not current.is_dir() or current.is_symlink():
        raise PersonalExtensionError("Personal extension storage has an unsafe parent.")
    for selected in reversed(missing):
        private_directory(selected)
    private_directory(directory)


def _bounded_command(command, maximum, timeout):
    """Stop a download before retaining unbounded subprocess output."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    chunks = []
    oversized = []

    def read_output():
        total = 0
        while True:
            chunk = process.stdout.read(65536)
            if not chunk:
                return
            total += len(chunk)
            if total > maximum:
                oversized.append(True)
                process.kill()
                return
            chunks.append(chunk)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.kill()
        process.wait()
        reader.join(timeout=5)
        raise PersonalExtensionError("The extension download timed out.") from error
    reader.join(timeout=5)
    if reader.is_alive() or oversized or process.returncode != 0:
        raise PersonalExtensionError("The extension download failed or exceeded its supported size limit.")
    return b"".join(chunks)


def profile_root(identity: dict, home: Path | None = None) -> Path:
    """Use machine-user storage, rejecting every enclosing versionable tree."""
    from environment_identity import _validated_identity
    user = _validated_identity(identity)
    lexical_home = Path(os.path.abspath(home or Path.home()))
    for ancestor in (lexical_home, *lexical_home.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise PersonalExtensionError("The machine-user home path contains a symbolic link.")
    selected_home = lexical_home.resolve(strict=True)
    if home is not None:
        base = selected_home / ".local/share"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", selected_home / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", selected_home / ".local/share"))
    if not base.is_absolute():
        raise PersonalExtensionError("Personal extension storage must be an absolute machine-user path.")
    base = Path(os.path.abspath(base)) / "gag-dev-team/users" / user["host"]
    for ancestor in (base, *base.parents):
        if ancestor.is_symlink():
            raise PersonalExtensionError("Personal extension storage contains a symbolic link.")
        if (ancestor / ".git").exists():
            raise PersonalExtensionError("Personal extensions cannot be stored inside a versionable repository.")
    _private_tree(base)
    matches = sorted(base.glob(f"{user['id']}--*"))
    if len(matches) > 1:
        raise PersonalExtensionError("Personal account storage is ambiguous.")
    root = matches[0] if matches else base / f"{user['id']}--{user['login'].lower()}"
    _private_tree(root)
    return root


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _publish(path: Path, payload: bytes):
    if path.is_symlink():
        raise PersonalExtensionError("Personal extension storage contains a symbolic link.")
    _private_tree(path.parent)
    from event_store import _publish_new
    if not _publish_new(path, payload) and path.read_bytes() != payload:
        raise PersonalExtensionError("An immutable personal extension version already has different content.")


def _read_receipt(root: Path, extension_id: str, digest: str):
    if not SLUG.fullmatch(extension_id) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise PersonalExtensionError("The extension reference is invalid.")
    directory = root / "extensions" / extension_id / "versions" / digest
    if any(path.is_symlink() for path in (directory, *directory.parents)):
        raise PersonalExtensionError("The extension version is unsafe.")
    receipt_path = directory / "receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.stat().st_size > 262144:
        raise PersonalExtensionError("The extension receipt is unsafe or exceeds its size limit.")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as error:
        raise PersonalExtensionError("The extension receipt is unreadable or corrupt.") from error
    if (not isinstance(receipt, dict) or not isinstance(receipt.get("source"), dict)
            or not isinstance(receipt.get("files"), dict) or not receipt["files"]
            or any(not isinstance(name, str) or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest) for name, digest in receipt["files"].items())):
        raise PersonalExtensionError("The extension receipt does not match its required structure.")
    files = receipt["files"]
    bundle_root = directory / "bundle"
    actual_files = set()
    for candidate in bundle_root.rglob("*"):
        if candidate.is_symlink():
            raise PersonalExtensionError("The extension bundle contains an unreviewed symbolic link.")
        if candidate.is_file():
            actual_files.add(candidate.relative_to(bundle_root).as_posix())
    if actual_files != set(files):
        raise PersonalExtensionError("The extension bundle contains missing or unreviewed files.")
    if hashlib.sha256(_canonical({"source": receipt["source"], "files": files})).hexdigest() != digest:
        raise PersonalExtensionError("The immutable extension receipt was altered.")
    for name, expected in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise PersonalExtensionError("The extension file path is unsafe.")
        path = directory / "bundle" / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise PersonalExtensionError("A personal extension file was altered.")
    if receipt.get("digest") != digest or receipt.get("extension_id") != extension_id:
        raise PersonalExtensionError("The extension receipt does not match its immutable reference.")
    if receipt.get("kind") == "skill":
        from user_skills import _parse_frontmatter
        name, _description, _body = _parse_frontmatter((bundle_root / "SKILL.md").read_text(encoding="utf-8"))
        if receipt.get("name") != name or extension_id != "personal-" + name:
            raise PersonalExtensionError("The skill receipt does not match its reviewed manifest.")
    elif receipt.get("kind") == "plugin":
        manifest_path = next((bundle_root / name for name in ("plugin.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json") if name in files), None)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path else {}
        name = manifest.get("name") if isinstance(manifest, dict) else None
        target = receipt.get("target")
        if (not isinstance(name, str) or not SLUG.fullmatch(name) or name.startswith("gag-dev-team")
                or not isinstance(target, str) or not TARGET.fullmatch(target) or target.split("@", 1)[0] != name
                or receipt.get("name") != name or extension_id != "personal-plugin-" + name
                or receipt.get("version") != manifest.get("version")):
            raise PersonalExtensionError("The plugin receipt does not match its reviewed manifest.")
    else:
        raise PersonalExtensionError("The extension receipt has an unsupported bundle kind.")
    return directory, receipt


def validate_source(binding: dict, source: dict):
    """Require bounded, credential-free provenance on the authenticated GitHub host."""
    if (not isinstance(source, dict) or set(source) - {"provider", "host", "repository", "path", "ref", "commit"}
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(source.get("repository", "")))
            or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit", "")))):
        raise PersonalExtensionError("A pinned GitHub repository and commit are required.")
    if source.get("host", binding["user"]["host"]) != binding["user"]["host"] or source.get("provider", "github") != "github":
        raise PersonalExtensionError("The skill source must use the verified account's GitHub host.")
    if any(part in {".", ".."} for part in source["repository"].split("/")):
        raise PersonalExtensionError("The repository source is invalid.")
    for field in ("path", "ref"):
        selected = source.get(field, "")
        if not isinstance(selected, str) or len(selected) > 300 or any(character in selected for character in ("\0", "\n", "\r", "@", ":", "\\")):
            raise PersonalExtensionError("The skill source path or ref is unsafe.")
    source_path = PurePosixPath(source.get("path", "."))
    if source_path.is_absolute() or ".." in source_path.parts:
        raise PersonalExtensionError("The repository-relative source path is unsafe.")


def stage_skill(binding: dict, source: dict, files: dict, home: Path | None = None):
    """Persist inert Markdown only; review must precede project activation."""
    validate_source(binding, source)
    if not isinstance(files, dict) or "SKILL.md" not in files or len(files) > 30:
        raise PersonalExtensionError("A skill must include SKILL.md and a bounded reference bundle.")
    encoded = {}
    for name, content in files.items():
        if name != "SKILL.md" and not re.fullmatch(r"references/[a-z0-9]+(?:-[a-z0-9]+)*\.(?:md|txt)", name):
            raise PersonalExtensionError("Personal skill bundles accept only SKILL.md and Markdown/text references; executable files require a supported reviewed adapter.")
        if not isinstance(content, str) or "\0" in content:
            raise PersonalExtensionError("Personal skill content must be UTF-8 text.")
        encoded[name] = content.encode("utf-8")
    if sum(map(len, encoded.values())) > 65536:
        raise PersonalExtensionError("The personal skill bundle exceeds its size limit.")
    from user_skills import _parse_frontmatter
    name, _description, _body = _parse_frontmatter(files["SKILL.md"])
    if not SLUG.fullmatch(name):
        raise PersonalExtensionError("The personal extension name must be an English slug.")
    extension_id = "personal-" + name
    digests = {key: hashlib.sha256(value).hexdigest() for key, value in encoded.items()}
    digest = hashlib.sha256(_canonical({"source": source, "files": digests})).hexdigest()
    receipt = {"extension_id": extension_id, "name": name, "kind": "skill", "source": source, "files": digests, "digest": digest}
    root = profile_root(binding["user"], home)
    with private_lock(root / "extensions.lock"):
        directory = root / "extensions" / extension_id / "versions" / digest
        for path, content in encoded.items():
            _publish(directory / "bundle" / path, content)
        _publish(directory / "receipt.json", _canonical(receipt))
    append_event(binding, {"event_type": "extension.downloaded", "data": {**receipt, "state": "downloaded"}}, f"download-{extension_id}-{digest}")
    return receipt


def download_extension(binding: dict, repository: str, path: str, ref: str = "HEAD", home: Path | None = None, kind="skill", target=None):
    """Resolve a GitHub ref, download bounded bytes, and stage inert skill sources."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise PersonalExtensionError("Provide an explicit GitHub owner/repository.")
    if any(part in {".", ".."} for part in repository.split("/")):
        raise PersonalExtensionError("The repository source is invalid.")
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or "\\" in path or (not relative.parts and kind != "plugin"):
        raise PersonalExtensionError("Provide a safe repository-relative skill path.")
    if not ref or len(ref) > 200 or ref.startswith("-"):
        raise PersonalExtensionError("The requested repository ref is invalid.")
    host = binding["user"]["host"]
    command = ["gh", "api", f"repos/{repository}/commits/{urllib.parse.quote(ref, safe='')}", "--hostname", host, "--jq", ".sha"]
    try:
        result = subprocess.run(command, capture_output=True, check=True, timeout=30)
        commit = result.stdout.decode("utf-8").strip()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("invalid commit")
        archive = _bounded_command(["gh", "api", f"repos/{repository}/zipball/{commit}", "--hostname", host], MAX_ARCHIVE_BYTES, 60)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        raise PersonalExtensionError("GitHub skill download failed; verify source access and authentication.") from error
    files = {}
    total_bytes = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            for entry in package.infolist():
                components = PurePosixPath(entry.filename).parts
                if not components:
                    continue
                selected = PurePosixPath(*components[1:])
                if not selected.is_relative_to(relative) or entry.is_dir():
                    continue
                name = selected.relative_to(relative).as_posix()
                if ".." in components or "\\" in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise PersonalExtensionError("The selected skill includes an unsafe archive entry.")
                total_bytes += entry.file_size
                maximum = 65536 if kind == "skill" else MAX_ARCHIVE_BYTES
                if entry.file_size > maximum or total_bytes > maximum or len(files) >= 1000:
                    raise PersonalExtensionError("The selected skill exceeds its size limit.")
                if name in files:
                    raise PersonalExtensionError("The skill archive contains duplicate entries.")
                content = package.read(entry)
                files[name] = content.decode("utf-8") if kind == "skill" else content
    except (zipfile.BadZipFile, UnicodeError) as error:
        raise PersonalExtensionError("The downloaded skill archive is invalid.") from error
    source = {"provider": "github", "host": host, "repository": repository, "path": path, "ref": ref, "commit": commit}
    if kind == "plugin":
        from native_extensions import stage_plugin
        return stage_plugin(binding, source, files, target, home)
    return stage_skill(binding, source, files, home)


def download_skill(binding: dict, repository: str, path: str, ref: str = "HEAD", home: Path | None = None):
    return download_extension(binding, repository, path, ref, home)


def review_extension(binding: dict, extension_id: str, digest: str, review: dict, home: Path | None = None):
    root = profile_root(binding["user"], home)
    _directory, receipt = _read_receipt(root, extension_id, digest)
    current = policy_snapshot()
    if review.get("policy_digest") != current["policy_digest"] or review.get("decision") not in {"accept", "reject", "unclear"}:
        raise PersonalExtensionError("Review must reference the current mandatory plugin policy and an explicit decision.")
    if not all(isinstance(review.get(key), str) and 1 <= len(review[key]) <= 1000 for key in ("reviewer", "reason")):
        raise PersonalExtensionError("Review requires a reviewer and compatibility rationale.")
    state = "reviewed" if review["decision"] == "accept" else "rejected"
    return append_event(binding, {"event_type": "extension.reviewed", "data": {**receipt, "state": state, "review": review}})


def activate_skill(binding: dict, extension_id: str, digest: str, home: Path | None = None):
    from environment_projection import read_snapshot
    root = profile_root(binding["user"], home)
    _directory, receipt = _read_receipt(root, extension_id, digest)
    if receipt.get("kind") != "skill":
        raise PersonalExtensionError("Native plugin bundles require a verified native adapter, not skill activation.")
    snapshot = read_snapshot(binding)
    matches = [item for item in snapshot["extensions"] if item.get("extension_id", item.get("id")) == extension_id and item.get("digest") == digest]
    if not matches or matches[-1].get("state") != "reviewed" or matches[-1].get("review", {}).get("policy_digest") != policy_snapshot()["policy_digest"]:
        raise PersonalExtensionError("A current accepting compatibility review is required before activation.")
    return append_event(binding, {"event_type": "extension.activated", "data": {**receipt, "state": "active", "review": matches[-1]["review"]}})


def load_personal_skill(binding: dict, extension_id: str, digest: str, home: Path | None = None):
    from environment_projection import read_snapshot
    matches = [item for item in read_snapshot(binding)["extensions"] if item.get("extension_id", item.get("id")) == extension_id and item.get("digest") == digest]
    if not matches or matches[-1].get("state") != "active" or matches[-1].get("review", {}).get("policy_digest") != policy_snapshot()["policy_digest"]:
        raise PersonalExtensionError("The personal extension is inactive or its mandatory-policy review is stale.")
    directory, receipt = _read_receipt(profile_root(binding["user"], home), extension_id, digest)
    if receipt.get("kind") != "skill":
        raise PersonalExtensionError("Native plugin bundles cannot be loaded as personal skills.")
    return {"namespace": extension_id, "files": {name: (directory / "bundle" / name).read_text(encoding="utf-8") for name in receipt["files"]}, "priority": "below-mandatory-plugin-policy"}


def _retain_native_bundle(profile, native_root, extension_id, target, harness, native_result):
    """Preserve verified host-managed source bytes without executing their contents."""
    if not isinstance(native_result, dict):
        return None
    installed_path = native_result.get("installedPath") or native_result.get("installPath")
    version = native_result.get("version")
    if not isinstance(installed_path, str) or not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,100}", version):
        return None
    source = Path(installed_path)
    cache = native_root / "plugins/cache"
    try:
        relative = source.relative_to(cache)
    except ValueError:
        raise PersonalExtensionError("The native installer reported a path outside its private plugin cache.")
    if len(relative.parts) != 3 or any(part in {".", ".."} for part in relative.parts):
        raise PersonalExtensionError("The native installer cache reference is invalid.")
    plugin_name, marketplace = target.split("@", 1)
    if relative.parts != (marketplace, plugin_name, version):
        raise PersonalExtensionError("The native installer returned a different target or version.")
    for ancestor in (source, *source.parents):
        if ancestor.is_symlink():
            raise PersonalExtensionError("The native plugin cache contains a symbolic link.")
    files = {}
    total_bytes = 0
    for candidate in sorted(source.rglob("*")):
        if candidate.is_symlink():
            raise PersonalExtensionError("Native plugin sources contain an unsafe symbolic link.")
        if not candidate.is_file():
            continue
        name = candidate.relative_to(source).as_posix()
        if any(part in {".git", "node_modules", ".next", "__pycache__"} or part.startswith(".env") for part in PurePosixPath(name).parts):
            raise PersonalExtensionError("Native plugin sources include private data or generated dependencies; preserve a clean reviewed source first.")
        total_bytes += candidate.stat().st_size
        if total_bytes > MAX_ARCHIVE_BYTES or len(files) >= 1000:
            raise PersonalExtensionError("The native plugin sources exceed the retention limit.")
        files[name] = candidate.read_bytes()
    if not files:
        return None
    digests = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    source_metadata = {"target": target, "harness": harness, "version": version}
    digest = hashlib.sha256(_canonical({"source": source_metadata, "files": digests})).hexdigest()
    directory = profile / "extensions" / extension_id / "versions" / digest
    with private_lock(profile / "extensions.lock"):
        for name, content in files.items():
            _publish(directory / "bundle" / name, content)
        _publish(directory / "receipt.json", _canonical({"source": source_metadata, "files": digests, "digest": digest, "kind": "plugin"}))
    return {"digest": digest, "version": version, "source": source_metadata, "retained": True}


def install_native_plugin(binding: dict, target: str, harness: str, review: dict, runner=subprocess.run, home: Path | None = None):
    """Use immutable reviewed source and an account-bound active native profile."""
    from native_extensions import install_plugin
    return install_plugin(binding, target, harness, review, runner, home)
