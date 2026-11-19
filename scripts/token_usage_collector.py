"""Keep registered Codex token sources synchronized while the local dashboard is healthy."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _is_process_running(process_id: int) -> bool:
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


def _read_service_state(path: Path) -> dict | None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        return None
    try:
        if path.stat().st_size > 16384:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _read_binding(path: Path) -> dict:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("The private collector binding is unsafe.")
    if path.stat().st_size > 16384:
        raise ValueError("The private collector binding is invalid.")
    supplied = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(supplied, dict) or not isinstance(supplied.get("user"), dict):
        raise ValueError("The private collector binding is invalid.")
    from environment_identity import project_binding
    verified = project_binding(supplied.get("project_root"), supplied["user"])
    expected_path = Path(verified["runtime_root"]) / "dashboard" / "collector-binding.json"
    if path.resolve(strict=True) != expected_path.resolve(strict=False):
        raise ValueError("The private collector binding is outside the selected account store.")
    if any(verified.get(key) != supplied.get(key) for key in verified):
        raise ValueError("The private collector binding does not match the project.")
    return verified


def run_collector(binding_file: str, interval: int = 60, collector_id: str | None = None) -> int:
    if not 15 <= interval <= 600:
        raise ValueError("Collector interval must be between 15 and 600 seconds.")
    try:
        from dashboard_service import _expected, _healthy
        from token_usage import record_collector_failure, sync_usage
        from user_rules import atomic_private_write

        binding = _read_binding(Path(binding_file))
        runtime = Path(binding["runtime_root"]) / "dashboard"
        service_path = runtime / "service.json"
        collector_path = runtime / "collector.json"
        while True:
            collector_state = _read_service_state(collector_path)
            if (collector_state is None or collector_state.get("collector_id") != collector_id
                    or collector_state.get("project_id") != binding["project_id"]
                    or collector_state.get("project_root") != binding["project_root"]
                    or collector_state.get("user_id") != binding["user"]["id"]):
                return 0
            state = _read_service_state(service_path)
            server_pid = state.get("pid") if isinstance(state, dict) else None
            if (state is None or isinstance(server_pid, bool) or not isinstance(server_pid, int)
                    or server_pid < 1 or not _is_process_running(server_pid)):
                return 0
            expected = _expected(binding, state.get("version"), state.get("source_hash"))
            if not _healthy(state, expected):
                return 0
            collector_state["pid"] = os.getpid()
            collector_state["status"] = "running"
            collector_state["last_check_at"] = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat()
            atomic_private_write(collector_path, json.dumps(collector_state).encode("utf-8"))
            try:
                sync_usage(binding, {})
            except Exception:
                # Never copy raw exceptions from local rollout parsing into a log.
                try:
                    record_collector_failure(binding, collector_id)
                except Exception:
                    pass
            collector_state["pid"] = os.getpid()
            collector_state["status"] = "running"
            collector_state["last_check_at"] = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat()
            atomic_private_write(collector_path, json.dumps(collector_state).encode("utf-8"))
            time.sleep(interval)
    except Exception:
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="token_usage_collector")
    parser.add_argument("--binding-file", required=True)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--collector-id", required=True)
    arguments = parser.parse_args(argv)
    return run_collector(arguments.binding_file, arguments.interval, arguments.collector_id)


if __name__ == "__main__":
    raise SystemExit(main())
