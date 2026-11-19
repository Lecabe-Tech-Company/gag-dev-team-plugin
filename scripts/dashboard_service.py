"""Build and reuse a protected loopback dashboard for one account and project."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

from user_rules import atomic_private_write, private_directory, private_lock

ROOT = Path(__file__).resolve().parent.parent
IGNORED = {"node_modules", ".next", ".git", "coverage", "__pycache__", "tests", "test-results", "playwright-report"}


class DashboardServiceError(RuntimeError):
    """A dashboard could not be started or authenticated."""


def source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in IGNORED for part in relative.parts):
            continue
        if path.is_symlink():
            raise DashboardServiceError("Dashboard sources cannot contain symbolic links.")
        if path.is_file():
            digest.update(relative.as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def select_node() -> tuple[Path, Path]:
    candidates = []
    current = shutil.which("node")
    if current:
        candidates.append(Path(current))
    candidates.extend(sorted((Path.home() / ".nvm/versions/node").glob("*/bin/node"), reverse=True))
    for node in candidates:
        try:
            output = subprocess.run([str(node), "--version"], capture_output=True, check=True, timeout=10)
            version = tuple(int(part) for part in output.stdout.decode().strip().lstrip("v").split(".")[:3])
            if version < (20, 9, 0):
                continue
            for npm in (node.parent / "node_modules/npm/bin/npm-cli.js", node.parent.parent / "lib/node_modules/npm/bin/npm-cli.js"):
                if npm.is_file():
                    return node.resolve(), npm.resolve()
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    raise DashboardServiceError("Node.js 20.9 or newer with npm is required. Install a compatible runtime and retry.")


def _expected(binding, version, source_hash):
    return {"service": "gag-personal-environment", "project_id": binding["project_id"],
            "user": {"host": binding["user"]["host"], "id": binding["user"]["id"]},
            "version": version, "source_hash": source_hash}


def _healthy(state, expected):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, stream, code, message, headers, new_url):
            return None

    try:
        if not isinstance(state, dict) or not isinstance(state.get("token"), str) or not state["token"]:
            return False
        port = state["port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            return False
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/health", headers={"Authorization": "Bearer " + state["token"]})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=2) as response:
            payload = json.loads(response.read(8192))
        return isinstance(payload, dict) and all(payload.get(key) == value for key, value in expected.items())
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return False


def ensure_dashboard(binding: dict, plugin_root: Path | None = None) -> dict:
    root = Path(plugin_root or ROOT).resolve()
    source = root / "dashboard"
    if not (source / "package-lock.json").is_file():
        raise DashboardServiceError("The installed plugin does not include dashboard sources and its lockfile.")
    version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    fingerprint = source_digest(source)
    runtime = Path(binding["runtime_root"]) / "dashboard"
    private_directory(runtime)
    expected = _expected(binding, version, fingerprint)
    with private_lock(runtime / "service.lock"):
        state_path = runtime / "service.json"
        if state_path.is_symlink():
            raise DashboardServiceError("Dashboard service metadata is unsafe.")
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = {}
        if _healthy(previous, expected):
            try:
                collector = ensure_token_usage_collector(binding, runtime, root)
            except DashboardServiceError:
                collector = {"status": "unavailable", "pid": None, "reused": False}
            return {"status": "running", "reused": True, "collector": collector,
                    "url": f"http://127.0.0.1:{previous['port']}/#access_token={previous['token']}"}
        node, npm = select_node()
        build = runtime / "builds" / fingerprint
        private_directory(build)
        environment = os.environ.copy()
        environment["PATH"] = str(node.parent) + os.pathsep + environment.get("PATH", "")
        environment["NEXT_TELEMETRY_DISABLED"] = "1"
        marker = build / "ready.json"
        if not marker.is_file():
            for path in source.rglob("*"):
                relative = path.relative_to(source)
                if any(part in IGNORED for part in relative.parts):
                    continue
                target = build / relative
                if path.is_dir():
                    private_directory(target)
                elif path.is_file():
                    private_directory(target.parent)
                    if target.is_symlink():
                        raise DashboardServiceError("Dashboard build cache contains a symbolic link.")
                    shutil.copyfile(path, target)
            with (runtime / "build.log").open("ab") as log:
                for arguments in (("ci", "--no-audit", "--no-fund"), ("run", "build")):
                    try:
                        subprocess.run([str(node), str(npm), *arguments], cwd=build, env=environment,
                                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
                    except (OSError, subprocess.SubprocessError) as error:
                        raise DashboardServiceError("Dashboard dependency installation or build failed; inspect the private build log.") from error
            atomic_private_write(marker, json.dumps({"source_hash": fingerprint}).encode("utf-8"))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        token = secrets.token_urlsafe(32)
        environment.update({"GAG_DASHBOARD_BINDING": json.dumps(binding), "GAG_DASHBOARD_TOKEN": token,
                            "GAG_DASHBOARD_PLUGIN_ROOT": str(root), "GAG_DASHBOARD_PYTHON": __import__("sys").executable,
                            "GAG_DASHBOARD_SOURCE_HASH": fingerprint, "GAG_DASHBOARD_VERSION": version,
                            "GAG_DASHBOARD_ALLOWED_HOST": f"127.0.0.1:{port}"})
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
        with (runtime / "server.log").open("ab") as log:
            process = subprocess.Popen([str(node), str(build / "node_modules/next/dist/bin/next"), "start", "--hostname", "127.0.0.1", "--port", str(port)],
                                       cwd=build, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **options)
        state = {"port": port, "token": token, "pid": process.pid, **expected}
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if _healthy(state, expected):
                atomic_private_write(state_path, json.dumps(state).encode("utf-8"))
                try:
                    collector = ensure_token_usage_collector(binding, runtime, root)
                except DashboardServiceError:
                    collector = {"status": "unavailable", "pid": None, "reused": False}
                return {"status": "running", "reused": False, "collector": collector,
                        "url": f"http://127.0.0.1:{port}/#access_token={token}"}
            if process.poll() is not None:
                break
            time.sleep(0.25)
        raise DashboardServiceError("The dashboard did not return its authenticated health identity. No unrelated process was stopped.")


def ensure_token_usage_collector(binding: dict, runtime: Path, plugin_root: Path | None = None,
                                 interval: int = 60) -> dict:
    """Start one private polling worker tied to the authenticated dashboard health check."""
    import datetime

    if not 15 <= interval <= 600:
        raise DashboardServiceError("The token collector interval is outside its safe range.")
    worker = Path(plugin_root or ROOT).resolve() / "scripts" / "token_usage_collector.py"
    if not worker.is_file() or worker.is_symlink():
        return {"status": "unavailable", "pid": None, "reused": False}
    state_path = runtime / "collector.json"
    binding_path = runtime / "collector-binding.json"
    private_directory(runtime)
    with private_lock(runtime / "collector.lock"):
        if state_path.is_symlink() or (hasattr(state_path, "is_junction") and state_path.is_junction()):
            raise DashboardServiceError("The private token usage collector state is unsafe.")
        try:
            current = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        process_id = current.get("pid")
        heartbeat = current.get("last_check_at")
        fresh = False
        if isinstance(heartbeat, str):
            try:
                instant = datetime.datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
                fresh = (datetime.datetime.now(datetime.timezone.utc) - instant).total_seconds() < interval * 4
            except ValueError:
                pass
        if (isinstance(process_id, int) and not isinstance(process_id, bool) and process_id > 0
                and fresh and _process_running(process_id)
                and current.get("project_id") == binding["project_id"]
                and current.get("user_id") == binding["user"]["id"]
                and current.get("project_root") == binding["project_root"]):
            return {"status": current.get("status", "starting"), "pid": process_id, "reused": True}
        collector_id = uuid.uuid4().hex
        try:
            atomic_private_write(binding_path, json.dumps(binding, sort_keys=True).encode("utf-8"))
        except Exception as error:
            raise DashboardServiceError("The private token usage collector binding could not be written.") from error
        state = {"pid": None, "collector_id": collector_id, "status": "starting", "project_id": binding["project_id"],
                 "project_root": binding["project_root"], "user_id": binding["user"]["id"],
                 "last_check_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        try:
            atomic_private_write(state_path, json.dumps(state).encode("utf-8"))
        except Exception as error:
            raise DashboardServiceError("The private token usage collector state could not be written.") from error
        environment = os.environ.copy()
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
        process = subprocess.Popen([__import__("sys").executable, str(worker), "--binding-file", str(binding_path),
                                    "--interval", str(interval), "--collector-id", collector_id],
                                   cwd=Path(plugin_root or ROOT).resolve(), env=environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   **options)
        state["pid"] = process.pid
        state["last_check_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            atomic_private_write(state_path, json.dumps(state).encode("utf-8"))
        except Exception as error:
            raise DashboardServiceError("The private token usage collector state could not be written.") from error
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if state_path.is_symlink() or (hasattr(state_path, "is_junction") and state_path.is_junction()):
                return {"status": "unavailable", "pid": None, "reused": False}
            try:
                current = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            if current.get("collector_id") != collector_id:
                return {"status": "unavailable", "pid": None, "reused": False}
            if current.get("status") == "running":
                return {"status": "running", "pid": process.pid, "reused": False}
            if process.poll() is not None:
                return {"status": "unavailable", "pid": None, "reused": False}
            time.sleep(0.1)
        return {"status": "starting", "pid": process.pid, "reused": False}


def _process_running(process_id: int) -> bool:
    if isinstance(process_id, bool) or not isinstance(process_id, int) or process_id < 1:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, process_id)
        if not handle:
            return False
        exit_code = wintypes.DWORD()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value == 259)
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False
