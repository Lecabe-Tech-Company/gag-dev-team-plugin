"""Dashboard startup uses real private locks, subprocesses and authenticated HTTP."""
from concurrent.futures import ThreadPoolExecutor
import importlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sys
import threading
from unittest import mock

from environment_fixtures import EnvironmentCase


SERVER_SOURCE = r'''
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, os, sys
from pathlib import Path
binding = json.loads(os.environ["GAG_DASHBOARD_BINDING"])
with Path("starts.log").open("a") as stream:
    stream.write(str(os.getpid()) + "\n")
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *arguments): pass
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + os.environ["GAG_DASHBOARD_TOKEN"]:
            self.send_response(401); self.end_headers(); return
        payload = {"service":"gag-personal-environment","project_id":binding["project_id"],
                   "user":{"id":binding["user"]["id"],"host":binding["user"]["host"]},
                   "version":os.environ["GAG_DASHBOARD_VERSION"],
                   "source_hash":os.environ["GAG_DASHBOARD_SOURCE_HASH"]}
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps(payload).encode())
HTTPServer(("127.0.0.1", int(sys.argv[sys.argv.index("--port")+1])), Handler).serve_forever()
'''


class DashboardLifecycleTests(EnvironmentCase):
    def setUp(self):
        super().setUp()
        self.service = importlib.import_module("dashboard_service")
        self.plugin = self.fake_home / "synthetic-plugin"
        dashboard = self.plugin / "dashboard"
        dashboard.mkdir(parents=True)
        (self.plugin / "package.json").write_text('{"version":"0.5.0"}', encoding="utf-8")
        (dashboard / "package-lock.json").write_text('{"lockfileVersion":3}', encoding="utf-8")
        self.npm = self.fake_home / "fake-npm.py"
        self.npm.write_text(
            "from pathlib import Path\nimport sys\n"
            "with Path('commands.log').open('a') as stream: stream.write(' '.join(sys.argv[1:])+'\\n')\n"
            "if sys.argv[1:3] == ['run','build']:\n"
            " target=Path('node_modules/next/dist/bin/next'); target.parent.mkdir(parents=True,exist_ok=True)\n"
            " target.write_text(" + repr(SERVER_SOURCE) + ",encoding='utf-8')\n", encoding="utf-8")
        self.process_ids = set()
        self.addCleanup(self.stop_fixture_servers)

    def stop_fixture_servers(self):
        runtime = Path(self.binding["runtime_root"]) / "dashboard"
        for path in runtime.glob("builds/*/starts.log"):
            self.process_ids.update(int(line) for line in path.read_text().splitlines())
        for process_id in self.process_ids:
            try:
                os.kill(process_id, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def test_concurrent_startup_builds_once_starts_once_and_reuses_same_authenticated_url(self):
        with mock.patch.object(self.service, "select_node", return_value=(Path(sys.executable), self.npm)):
            with ThreadPoolExecutor(max_workers=3) as pool:
                results = list(pool.map(lambda _: self.service.ensure_dashboard(self.binding, self.plugin), range(3)))
            again = self.service.ensure_dashboard(self.binding, self.plugin)
        self.assertEqual(len({result["url"] for result in results + [again]}), 1)
        self.assertEqual(sum(not result["reused"] for result in results), 1)
        self.assertTrue(again["reused"])
        runtime = Path(self.binding["runtime_root"]) / "dashboard"
        state = json.loads((runtime / "service.json").read_text())
        self.process_ids.add(state["pid"])
        build = runtime / "builds" / state["source_hash"]
        self.assertEqual((build / "commands.log").read_text().splitlines(),
                         ["ci --no-audit --no-fund", "run build"])
        self.assertEqual(len((build / "starts.log").read_text().splitlines()), 1)
        self.assertTrue(self.service._healthy(state, self.service._expected(
            self.binding, "0.5.0", self.service.source_digest(self.plugin / "dashboard"))))

    def test_failed_dependency_install_returns_no_url_or_ready_marker(self):
        self.npm.write_text("raise SystemExit(7)\n", encoding="utf-8")
        with mock.patch.object(self.service, "select_node", return_value=(Path(sys.executable), self.npm)):
            with self.assertRaises(self.service.DashboardServiceError):
                self.service.ensure_dashboard(self.binding, self.plugin)
        runtime = Path(self.binding["runtime_root"]) / "dashboard"
        self.assertFalse((runtime / "service.json").exists())
        self.assertEqual(list(runtime.glob("builds/*/ready.json")), [])

    def test_unrelated_service_is_not_reused_or_stopped(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_arguments):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"service":"unrelated"}')

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        runtime = Path(self.binding["runtime_root"]) / "dashboard"
        runtime.mkdir()
        (runtime / "service.json").write_text(json.dumps({
            "port": server.server_port, "token": "synthetic-unrelated", "pid": os.getpid()}), encoding="utf-8")
        with mock.patch.object(self.service, "select_node", return_value=(Path(sys.executable), self.npm)):
            result = self.service.ensure_dashboard(self.binding, self.plugin)
        self.assertFalse(result["reused"])
        self.assertNotIn(":" + str(server.server_port) + "/", result["url"])
        self.assertTrue(thread.is_alive())

