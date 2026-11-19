"""Loopback health identity, redirects and process metadata use synthetic services."""
import importlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import threading
import unittest

from test_project_cli import ROOT

sys.path.insert(0, str(ROOT / "scripts"))


class DashboardHealthTests(unittest.TestCase):
    def setUp(self):
        self.service = importlib.import_module("dashboard_service")
        self.binding = {"project_id": "synthetic-project", "user": {"host": "github.com", "id": 101, "login": "qa-first"}}
        self.expected = self.service._expected(self.binding, "0.5.0", "synthetic-source-hash")
        self.headers = []

    def server(self, payload=None, redirect=None):
        received = self.headers

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_arguments):
                pass

            def do_GET(self):
                received.append({"path": self.path, "authorization": self.headers.get("Authorization")})
                if redirect is not None:
                    self.send_response(302)
                    self.send_header("Location", redirect)
                    self.end_headers()
                    return
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_port

    def test_health_reuses_only_the_expected_account_project_version_and_sources(self):
        port = self.server(self.expected)
        state = {"port": port, "token": "synthetic-local-capability"}
        self.assertTrue(self.service._healthy(state, self.expected))
        self.assertEqual(self.headers[0]["authorization"], "Bearer synthetic-local-capability")
        for field, value in (("project_id", "another-project"), ("version", "another-version"),
                             ("source_hash", "another-source"), ("user", {"host": "github.com", "id": 202})):
            with self.subTest(field=field):
                wrong = dict(self.expected, **{field: value})
                self.assertFalse(self.service._healthy(state, wrong))

    def test_redirects_do_not_receive_the_local_capability_or_count_as_health(self):
        target = self.server(self.expected)
        redirect = self.server(redirect="http://127.0.0.1:" + str(target) + "/api/health")
        state = {"port": redirect, "token": "synthetic-local-capability"}
        healthy = self.service._healthy(state, self.expected)
        self.assertFalse(healthy)
        self.assertEqual(len(self.headers), 1, "Health requests must not follow a foreign service redirect")

    def test_json_from_a_different_service_is_not_a_dashboard(self):
        for payload in ([], True, None, {"service": "another-service"}):
            with self.subTest(payload=payload):
                port = self.server(payload)
                self.assertFalse(self.service._healthy({"port": port, "token": "synthetic"}, self.expected))

    def test_malformed_process_metadata_is_not_a_healthy_instance(self):
        for state in (None, [], {}, {"port": True, "token": "synthetic"},
                      {"port": "1234", "token": "synthetic"}, {"port": 1234, "token": 42}):
            with self.subTest(state=state):
                self.assertFalse(self.service._healthy(state, self.expected))
