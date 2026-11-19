"""Install reviewed immutable plugins through account-bound native profiles."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from event_store import append_event
from user_rules import policy_snapshot, private_lock
from personal_extensions import (
    MAX_ARCHIVE_BYTES, SLUG, TARGET, PersonalExtensionError, _canonical, _private_tree,
    _publish, _read_receipt, _retain_native_bundle, profile_root, validate_source,
)


def stage_plugin(binding, source, files, target, home=None):
    """Store source bytes without running package scripts, hooks, or installers."""
    validate_source(binding, source)
    if not isinstance(target, str) or not TARGET.fullmatch(target):
        raise PersonalExtensionError("A plugin@marketplace target is required for pinned plugin sources.")
    if not isinstance(files, dict) or not files or len(files) > 1000:
        raise PersonalExtensionError("A bounded plugin source bundle is required.")
    encoded = {}
    total = 0
    for name, content in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts or "\\" in name:
            raise PersonalExtensionError("The plugin source contains an unsafe path.")
        if any(part in {".git", "node_modules", ".next", "__pycache__"} or part.startswith(".env") for part in relative.parts):
            raise PersonalExtensionError("Plugin sources cannot include private data or generated dependencies.")
        if not isinstance(content, (str, bytes)):
            raise PersonalExtensionError("Plugin source files must contain bytes or UTF-8 text.")
        encoded[name] = content.encode("utf-8") if isinstance(content, str) else content
        total += len(encoded[name])
        if total > MAX_ARCHIVE_BYTES:
            raise PersonalExtensionError("The pinned plugin source bundle exceeds its size limit.")
    manifest_name = next((name for name in ("plugin.json", ".codex-plugin/plugin.json", ".claude-plugin/plugin.json") if name in encoded), None)
    try:
        manifest = json.loads(encoded[manifest_name]) if manifest_name else None
    except (ValueError, UnicodeError) as error:
        raise PersonalExtensionError("The pinned plugin manifest is invalid.") from error
    name = manifest.get("name") if isinstance(manifest, dict) else None
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(name, str) or not SLUG.fullmatch(name) or name != target.split("@", 1)[0]:
        raise PersonalExtensionError("The pinned manifest does not match the requested plugin.")
    if name.startswith("gag-dev-team"):
        raise PersonalExtensionError("Personal plugins cannot replace mandatory GAG Dev Team policies.")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,100}", version):
        raise PersonalExtensionError("A pinned plugin manifest version is required.")
    extension_id = "personal-plugin-" + name
    digests = {name: hashlib.sha256(content).hexdigest() for name, content in encoded.items()}
    digest = hashlib.sha256(_canonical({"source": source, "files": digests})).hexdigest()
    receipt = {"extension_id": extension_id, "name": name, "kind": "plugin", "version": version,
               "target": target, "source": source, "files": digests, "digest": digest}
    profile = profile_root(binding["user"], home)
    with private_lock(profile / "extensions.lock"):
        directory = profile / "extensions" / extension_id / "versions" / digest
        for filename, content in encoded.items():
            _publish(directory / "bundle" / filename, content)
        _publish(directory / "receipt.json", _canonical(receipt))
    append_event(binding, {"event_type": "extension.downloaded", "data": {**receipt, "state": "downloaded"}}, "download-" + extension_id + "-" + digest)
    return receipt


def native_profile(binding, harness, home=None):
    if harness not in {"codex", "claude"}:
        raise PersonalExtensionError("This host has no verified native plugin adapter.")
    profile = profile_root(binding["user"], home) / "native" / harness
    _private_tree(profile)
    marker = {"provider": "github", "host": binding["user"]["host"], "id": binding["user"]["id"], "harness": harness}
    _publish(profile / "account.json", _canonical(marker))
    return profile


def _pinned_marketplace(profile, receipt, directory, harness):
    digest = receipt["digest"]
    name = "personal-" + digest[:24]
    root = profile / "catalogs" / digest / harness
    plugin_path = root / "plugins" / receipt["name"]
    for filename, expected in receipt["files"].items():
        content = (directory / "bundle" / filename).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise PersonalExtensionError("The pinned plugin changed while preparing its local catalog.")
        _publish(plugin_path / filename, content)
    if harness == "codex":
        index = {"name": name, "interface": {"displayName": "Personal reviewed plugin"}, "plugins": [{
            "name": receipt["name"], "source": {"source": "local", "path": "./plugins/" + receipt["name"]},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}]}
        location = root / ".agents/plugins/marketplace.json"
    else:
        index = {"name": name, "owner": {"name": "Personal profile"}, "plugins": [{
            "name": receipt["name"], "source": "./plugins/" + receipt["name"], "version": receipt["version"]}]}
        location = root / ".claude-plugin/marketplace.json"
    _publish(location, _canonical(index))
    expected_paths = {location.relative_to(root).as_posix()} | {"plugins/" + receipt["name"] + "/" + name for name in receipt["files"]}
    actual_paths = set()
    for candidate in root.rglob("*"):
        if candidate.is_symlink():
            raise PersonalExtensionError("The pinned marketplace contains an unsafe symbolic link.")
        if candidate.is_file():
            actual_paths.add(candidate.relative_to(root).as_posix())
    if actual_paths != expected_paths:
        raise PersonalExtensionError("The pinned marketplace contains unreviewed files.")
    return root, receipt["name"] + "@" + name


def install_plugin(binding, target, harness, review, runner=subprocess.run, home=None):
    if not isinstance(target, str) or not TARGET.fullmatch(target) or target.split("@", 1)[0].startswith("gag-dev-team"):
        raise PersonalExtensionError("A personal plugin cannot replace a mandatory plugin or use an invalid target.")
    if harness not in {"codex", "claude"}:
        raise PersonalExtensionError("This host has no verified native plugin adapter.")
    profile = profile_root(binding["user"], home)
    identifier = review.get("extension_id") if isinstance(review, dict) else None
    digest = review.get("content_digest") if isinstance(review, dict) else None
    details = {"extension_id": identifier or "personal-plugin-" + target.split("@", 1)[0], "kind": "plugin", "name": target,
               "source": {"target": target, "harness": harness}, "state": "pending_verification", "activation_verified": False}
    if not identifier or not digest:
        return append_event(binding, {"event_type": "extension.discovered", "data": details})
    directory, receipt = _read_receipt(profile, identifier, digest)
    if receipt.get("kind") != "plugin" or receipt.get("target") != target:
        raise PersonalExtensionError("The reviewed artifact does not match the requested native plugin.")
    from environment_projection import read_snapshot
    matches = [item for item in read_snapshot(binding)["extensions"] if item.get("extension_id") == identifier and item.get("digest") == digest]
    current = matches[0] if matches else {}
    if current.get("state") not in {"reviewed", "pending_profile", "pending_auth", "pending_trust", "pending_host", "pending_restart", "pending_verification", "failed"} or current.get("review", {}).get("decision") != "accept" or current.get("review", {}).get("policy_digest") != policy_snapshot()["policy_digest"]:
        raise PersonalExtensionError("The exact pinned plugin source needs a current accepting compatibility review.")
    native_root = native_profile(binding, harness, home)
    variable = "CODEX_HOME" if harness == "codex" else "CLAUDE_CONFIG_DIR"
    active = os.environ.get(variable)
    details.update({**receipt, "review": current["review"], "native_profile": str(native_root), "profile_variable": variable})
    if not active or Path(os.path.abspath(active)) != native_root:
        details["state"] = "pending_profile"
        return append_event(binding, {"event_type": "extension.discovered", "data": details})
    if not shutil.which(harness):
        details["state"] = "pending_host"
        return append_event(binding, {"event_type": "extension.discovered", "data": details})
    marketplace, pinned_target = _pinned_marketplace(profile, receipt, directory, harness)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment[variable] = str(native_root)
    commands = [[harness, "plugin", "marketplace", "add", str(marketplace), "--json"],
                (["codex", "plugin", "add", pinned_target, "--json"] if harness == "codex" else ["claude", "plugin", "install", pinned_target, "--scope", "user", "--json"])]
    details["state"] = "failed"
    try:
        for command in commands:
            result = runner(command, capture_output=True, timeout=120, check=False, cwd=native_root, env=environment)
            try:
                outcome = json.loads(result.stdout)
            except (ValueError, TypeError):
                outcome = {}
            if not isinstance(outcome, dict):
                outcome = {}
            if outcome.get("status") in {"pending_auth", "pending_trust"}:
                details["state"] = outcome["status"]
                break
            if result.returncode != 0:
                break
        else:
            retained = _retain_native_bundle(profile, native_root, identifier, pinned_target, harness, outcome)
            if retained:
                installed = profile / "extensions" / identifier / "versions" / retained["digest"] / "receipt.json"
                observed = json.loads(installed.read_text(encoding="utf-8"))
                details["state"] = "pending_restart" if observed["files"] == receipt["files"] else "pending_verification"
                details["retained_native_digest"] = retained["digest"]
            else:
                details["state"] = "pending_verification"
    except subprocess.TimeoutExpired:
        details["state"] = "pending_verification"
    except (OSError, PersonalExtensionError):
        details["state"] = "failed"
    details["native_target"] = pinned_target
    return append_event(binding, {"event_type": "extension.installed" if details["state"] == "pending_restart" else "extension.discovered", "data": details})
