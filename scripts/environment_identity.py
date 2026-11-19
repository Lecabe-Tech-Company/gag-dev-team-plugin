"""Resolve authenticated identities and account-scoped Git metadata paths."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


class EnvironmentIdentityError(RuntimeError):
    """Raised when an authenticated account or private project root is unsafe."""


_HOST_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,39}$")


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_"):
            environment.pop(name, None)
    return environment


def _run_command(command: list[str], runner=subprocess.run) -> subprocess.CompletedProcess:
    try:
        return runner(command, capture_output=True, check=True, timeout=15, env=_git_environment())
    except (OSError, subprocess.SubprocessError) as error:
        raise EnvironmentIdentityError("Authenticated GitHub identity could not be verified.") from error


def _host_value(host: str | None) -> str:
    selected = host or os.environ.get("GH_HOST") or "github.com"
    if not isinstance(selected, str) or not _HOST_PATTERN.fullmatch(selected):
        raise EnvironmentIdentityError("The GitHub host is invalid.")
    return selected.lower()


def resolve_identity(host: str | None = None, runner=subprocess.run) -> dict:
    """Read the logged-in account from GitHub CLI without exposing credentials."""
    selected_host = _host_value(host)
    command = ["gh", "api", "user", "--hostname", selected_host]
    result = _run_command(command, runner)
    try:
        payload = json.loads(result.stdout.decode("utf-8", errors="strict"))
        account_id = payload["id"]
        login = payload["login"]
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise EnvironmentIdentityError("GitHub returned an invalid authenticated-user response.") from error
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise EnvironmentIdentityError("GitHub returned an invalid account ID.")
    if not isinstance(login, str) or not _LOGIN_PATTERN.fullmatch(login):
        raise EnvironmentIdentityError("GitHub returned an invalid account login.")
    return {"provider": "github", "host": selected_host, "id": account_id, "login": login}


def _git_path(project: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project), *arguments], capture_output=True, check=True,
            timeout=10, env=_git_environment(),
        )
        return result.stdout.decode("utf-8", errors="strict").strip()
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise EnvironmentIdentityError("The selected project must be inside a valid Git worktree.") from error


def _is_link(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()) or (
            path.resolve(strict=False) != Path(os.path.abspath(path))
        )
    except OSError:
        return True


def _ensure_private_directory(path: Path, allowed_root: Path) -> None:
    current = allowed_root
    relative = path.relative_to(allowed_root)
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise EnvironmentIdentityError("The private account storage path contains a symbolic link.")
        try:
            current.mkdir(mode=0o700, exist_ok=True)
        except OSError as error:
            raise EnvironmentIdentityError("The private account storage directory cannot be created safely.") from error
        if _is_link(current) or not current.is_dir():
            raise EnvironmentIdentityError("The private account storage directory is unsafe.")
        if os.name != "nt":
            try:
                os.chmod(current, 0o700)
            except OSError as error:
                raise EnvironmentIdentityError("Private account storage permissions could not be secured.") from error


def _validated_identity(identity: dict) -> dict:
    if not isinstance(identity, dict) or identity.get("provider") != "github":
        raise EnvironmentIdentityError("A verified GitHub identity is required.")
    supplied_host = identity.get("host")
    if not isinstance(supplied_host, str) or not supplied_host:
        raise EnvironmentIdentityError("A verified GitHub host is required.")
    host = _host_value(supplied_host)
    account_id = identity.get("id")
    login = identity.get("login")
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
        raise EnvironmentIdentityError("A verified numeric GitHub account ID is required.")
    if not isinstance(login, str) or not _LOGIN_PATTERN.fullmatch(login):
        raise EnvironmentIdentityError("A verified GitHub login is required.")
    return {"provider": "github", "host": host, "id": account_id, "login": login}


def project_binding(project: str | os.PathLike, identity: dict) -> dict:
    """Bind a project to one verified account under non-versionable Git metadata."""
    user = _validated_identity(identity)
    try:
        project_path = Path(project).expanduser().resolve(strict=True)
        if not project_path.is_dir():
            raise OSError("not a directory")
    except (OSError, RuntimeError) as error:
        raise EnvironmentIdentityError("The selected project directory cannot be resolved safely.") from error

    try:
        top_level = Path(_git_path(project_path, "rev-parse", "--show-toplevel")).resolve(strict=True)
        common_directory = Path(_git_path(
            project_path, "rev-parse", "--path-format=absolute", "--git-common-dir"
        )).resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise EnvironmentIdentityError("The Git metadata path cannot be resolved safely.") from error
    expected_git_directory = (top_level / ".git").resolve(strict=False)
    if common_directory == top_level or (
        common_directory.is_relative_to(top_level) and common_directory != expected_git_directory
    ):
        raise EnvironmentIdentityError("Git metadata is inside the versionable project tree.")

    for ancestor in common_directory.parents:
        marker = ancestor / ".git"
        if not (marker.exists() or marker.is_file()):
            continue
        try:
            enclosing_root = Path(_git_path(ancestor, "rev-parse", "--show-toplevel")).resolve(strict=True)
        except EnvironmentIdentityError:
            continue
        metadata_path = (enclosing_root / ".git").resolve(strict=False)
        if common_directory.is_relative_to(enclosing_root) and not common_directory.is_relative_to(metadata_path):
            raise EnvironmentIdentityError("Git common metadata is inside another versionable worktree.")

    # Reuse the existing storage-root validator for the shared safe Git metadata boundary.
    try:
        from user_rules import private_storage_root
    except ModuleNotFoundError:
        from scripts.user_rules import private_storage_root
    try:
        users_root = private_storage_root(project_path, "users")
    except Exception as error:
        raise EnvironmentIdentityError("The private Git metadata root is unsafe.") from error
    storage_root = users_root.parent.parent
    _ensure_private_directory(users_root.parent, common_directory)
    _ensure_private_directory(users_root, common_directory)
    host_root = users_root / user["host"]
    _ensure_private_directory(host_root, users_root)
    existing_accounts = sorted(
        path for path in host_root.glob(f"{user['id']}--*")
        if path.is_dir() and not _is_link(path)
    )
    if len(existing_accounts) > 1:
        raise EnvironmentIdentityError("Multiple private account roots share the verified GitHub ID.")
    account_root = existing_accounts[0] if existing_accounts else host_root / f"{user['id']}--{user['login'].lower()}"
    project_id = "git-" + hashlib.sha256(str(common_directory).encode("utf-8")).hexdigest()[:24]
    project_root = account_root / "projects" / project_id
    events_root = project_root / "events"
    versions_root = project_root / "versions"
    runtime_root = project_root / "runtime"
    _ensure_private_directory(project_root, users_root)
    for directory in (events_root, versions_root, runtime_root):
        _ensure_private_directory(directory, users_root)
    binding = {
        "project_id": project_id,
        "project_root": str(top_level),
        "private_root": str(project_root),
        "user": user,
        "account_root": str(account_root),
        "events_root": str(events_root),
        "versions_root": str(versions_root),
        "runtime_root": str(runtime_root),
        "git_common_dir": str(common_directory),
        "storage_root": str(storage_root),
    }
    try:
        try:
            from event_store import append_event
        except ModuleNotFoundError:
            from scripts.event_store import append_event
        append_event(binding, {
            "event_type": "identity.observed",
            "summary": "Verified the active GitHub account for this project environment.",
            "data": {"login": user["login"], "host": user["host"]},
        }, event_id=f"identity-{user['id']}-{hashlib.sha256(user['login'].encode('utf-8')).hexdigest()[:12]}")
    except ImportError:
        # The identity module remains usable while the event store is being packaged.
        pass
    return binding
