"""Limited collector lifecycle uses authenticated loopback health and private fixtures."""
import contextlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from test_project_cli import ROOT
from token_usage_fixtures import TokenUsageCase, PRIVATE_MARKER, response


class ProcessStatusTests(unittest.TestCase):
    def test_process_status_tracks_an_owned_child_for_service_and_collector(self):
        service = importlib.import_module("dashboard_service")
        collector = importlib.import_module("token_usage_collector")
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, **options)
        try:
            self.assertTrue(service._process_running(child.pid))
            self.assertTrue(collector._is_process_running(child.pid))
        finally:
            child.terminate()
            child.wait(timeout=5)
        self.assertFalse(service._process_running(child.pid))
        self.assertFalse(collector._is_process_running(child.pid))
        self.assertFalse(service._process_running(0))
        self.assertFalse(collector._is_process_running(0))


class TokenCollectorTests(TokenUsageCase):
    def setUp(self):
        super().setUp()
        self.service = importlib.import_module("dashboard_service")
        self.collector = importlib.import_module("token_usage_collector")
        self.runtime = Path(self.binding["runtime_root"]) / "dashboard"
        self.runtime.mkdir()
        self.binding_path = self.runtime / "collector-binding.json"
        self.binding_path.write_text(json.dumps(self.binding), encoding="utf-8")
        self.expected = self.service._expected(self.binding, "0.5.0", "synthetic-collector-source")
        expected = self.expected
        capability = "synthetic-collector-capability"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_arguments):
                pass

            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer " + capability:
                    self.send_response(401)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(expected).encode("utf-8"))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.service_state = {"pid": os.getpid(), "port": self.server.server_port,
                              "token": capability, **self.expected}
        self.write_service(self.service_state)
        self.owned_processes = []
        self.addCleanup(self.stop_owned_processes)

    def write_service(self, value):
        (self.runtime / "service.json").write_text(json.dumps(value), encoding="utf-8")

    def stop_owned_processes(self):
        for process in self.owned_processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)

    def wait_for(self, condition, timeout=22):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail("The synthetic collector did not reach its expected state before the deadline")

    def collector_state(self):
        try:
            return json.loads((self.runtime / "collector.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def prepare_worker_state(self):
        state = {"pid": os.getpid(), "collector_id": "11111111111111111111111111111111",
                 "project_id": self.binding["project_id"], "user_id": self.binding["user"]["id"],
                 "project_root": self.binding["project_root"],
                 "last_check_at": datetime.now(timezone.utc).isoformat()}
        (self.runtime / "collector.json").write_text(json.dumps(state), encoding="utf-8")

    def prepare_response(self):
        path = self.create_source()
        self.add_context(path)
        self.start_goal()
        self.append_records(path, response())
        return path

    def test_real_worker_updates_registered_sources_reuses_process_and_does_not_repeat_history(self):
        path = self.prepare_response()
        actual_popen = subprocess.Popen

        def start_process(*arguments, **options):
            process = actual_popen(*arguments, **options)
            self.owned_processes.append(process)
            return process

        with mock.patch.object(self.service.subprocess, "Popen", side_effect=start_process):
            started = self.service.ensure_token_usage_collector(self.binding, self.runtime, ROOT, interval=15)
        self.wait_for(lambda: self.own()["response_count"] == 1)
        reused = self.service.ensure_token_usage_collector(self.binding, self.runtime, ROOT, interval=15)
        self.assertTrue(reused["reused"])
        self.assertEqual(reused["pid"], started["pid"])
        self.append_records(path, response(response_id="response-two"))
        self.wait_for(lambda: self.own()["response_count"] == 2)
        self.wait_for(lambda: self.collector_state().get("last_check_at", "") >= self.snapshot()["last_synced_at"])
        before = self.history_bytes()
        heartbeat = self.collector_state()["last_check_at"]
        self.wait_for(lambda: self.collector_state().get("last_check_at", "") > heartbeat)
        self.assertEqual(self.history_bytes(), before)
        self.assertEqual(self.own()["total_tokens"], 240)
        self.assertEqual(len(self.owned_processes), 1)

    def test_worker_stops_before_another_sync_when_bearer_health_fails(self):
        path = self.prepare_response()
        self.prepare_worker_state()

        def lose_health(_interval):
            self.append_records(path, response(response_id="must-not-be-collected"))
            self.write_service({**self.service_state, "token": "incorrect-capability"})

        with mock.patch.object(self.collector.time, "sleep", side_effect=lose_health):
            result = self.collector.run_collector(str(self.binding_path), interval=15, collector_id="11111111111111111111111111111111")
        self.assertEqual(result, 0)
        self.assertEqual(self.own()["response_count"], 1)

    def test_replaced_worker_never_overwrites_the_new_collector_identity(self):
        self.prepare_worker_state()

        def replace_identity(_interval):
            state = self.collector_state()
            state["collector_id"] = "22222222222222222222222222222222"
            (self.runtime / "collector.json").write_text(json.dumps(state), encoding="utf-8")

        with mock.patch.object(self.collector.time, "sleep", side_effect=replace_identity):
            result = self.collector.run_collector(str(self.binding_path), interval=15, collector_id="11111111111111111111111111111111")
        self.assertEqual(result, 0)
        self.assertEqual(self.collector_state()["collector_id"], "22222222222222222222222222222222")

    def test_sync_failure_is_visible_without_logging_or_persisting_private_exception_content(self):
        self.prepare_response()
        self.tokens.sync_usage(self.binding, {})
        synced_at = self.snapshot()["last_synced_at"]
        before = self.history_bytes()
        self.prepare_worker_state()

        def replace_identity(_interval):
            state = self.collector_state()
            state["collector_id"] = "22222222222222222222222222222222"
            (self.runtime / "collector.json").write_text(json.dumps(state), encoding="utf-8")

        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.object(self.tokens, "sync_usage", side_effect=RuntimeError(PRIVATE_MARKER)), \
                mock.patch.object(self.collector.time, "sleep", side_effect=replace_identity), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = self.collector.run_collector(str(self.binding_path), interval=15, collector_id="11111111111111111111111111111111")
        self.assertEqual(result, 0)
        self.assertNotIn(PRIVATE_MARKER, output.getvalue() + errors.getvalue())
        snapshot = self.snapshot()
        self.assertIn(snapshot["status"], {"partial", "stale", "unavailable", "incompatible"})
        self.assertEqual(snapshot["last_synced_at"], synced_at)
        self.assertEqual(snapshot["totals"]["own"]["total_tokens"], 120)
        self.assert_history_preserved(before)
        self.assert_private_content_absent()

