"""ESP-066 integration contracts. Fake credentials; no external services."""
import http.client
import importlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
TOKEN = "test-only-esp066-not-a-real-token"


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gag qa spaces ")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.install = importlib.import_module("project_install")

    def snapshot(self):
        return {str(p.relative_to(self.project)): p.read_bytes()
                for p in self.project.rglob("*") if p.is_file() and ".git" not in p.parts}


class InstallationTests(ProjectCase):
    def test_install_preserves_user_configuration_and_is_idempotent(self):
        (self.project / "AGENTS.md").write_text("# My project\nKeep these instructions.\n")
        config = self.project / ".codex/config.toml"
        config.parent.mkdir()
        config.write_text('model = "existing-model"\n[mcp_servers.other]\nurl = "https://example.invalid/mcp"\n')
        runtime = self.install.install(self.project, source=ROOT)
        self.assertTrue(runtime.is_dir())
        self.assertEqual(len(list((self.project / ".codex/agents").glob("gag-*.toml"))), 5)
        self.assertIn("Keep these instructions.", (self.project / "AGENTS.md").read_text())
        parsed = tomllib.loads(config.read_text())
        self.assertEqual(parsed["model"], "existing-model")
        self.assertEqual(parsed["mcp_servers"]["other"]["url"], "https://example.invalid/mcp")
        before = self.snapshot()
        self.assertEqual(self.install.install(self.project, source=ROOT), runtime)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(any("caveman" in str(p).lower() for p in self.project.rglob("SKILL.md")))

    def test_profile_conflict_does_not_partially_install(self):
        conflict = self.project / ".codex/agents/gag-documentador.toml"
        conflict.parent.mkdir(parents=True)
        conflict.write_text('custom = true\n')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.install.install(self.project, source=ROOT)
        self.assertEqual(self.snapshot(), before)

    def test_external_symlink_does_not_write_outside_project(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.project / ".gag-dev-team").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                self.install.install(self.project, source=ROOT)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_token_is_private_ignored_and_absent_from_public_configs(self):
        self.install.install(self.project, source=ROOT)
        self.install.configure_scripta(self.project, TOKEN)
        secret = self.project / ".gag-dev-team/scripta-token"
        self.assertEqual(secret.read_text().strip(), TOKEN)
        self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
        result = subprocess.run(["git", "check-ignore", "--", str(secret)], cwd=self.project, capture_output=True)
        self.assertEqual(result.returncode, 0)
        public = [self.project / ".codex/config.toml", self.project / ".codex/hooks.json", self.project / "AGENTS.md"]
        for path in public:
            if path.exists():
                self.assertNotIn(TOKEN, path.read_text())
        config = tomllib.loads(public[0].read_text())
        docs = config["mcp_servers"]["docs"]
        self.assertEqual(docs["url"], "https://scripta-mcp.lecabe.com.br/mcp")
        self.assertIn("http_headers_helper", docs)


class HttpTests(ProjectCase):
    def start(self, installer):
        self.install.install(self.project, source=ROOT)
        module = importlib.import_module("gag_dev_team")
        self.server = module.create_server(self.project, graphify_installer=installer)
        self.addCleanup(self.server.server_close)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.shutdown)
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)
        self.prefix = "/" + self.server.session + "/"

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read().decode()
        finally:
            connection.close()

    def save(self, token=TOKEN, headers=None, body=None):
        defaults = {"Origin": self.origin, "X-GAG-Session": self.server.session, "Content-Type": "application/json"}
        if headers:
            defaults.update(headers)
        return self.request("POST", self.prefix + "api/save", json.dumps({"token": token}) if body is None else body, defaults)

    def wait_state(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status, body = self.request("GET", self.prefix + "api/status", headers={"X-GAG-Session": self.server.session})
            self.assertEqual(status, 200)
            data = json.loads(body)
            if data.get("status") in ("done", "error") or data.get("state") in ("done", "error"):
                return data
            time.sleep(0.01)
        self.fail("Background job did not reach terminal state")

    def test_page_and_rejected_requests_have_no_secret_side_effect(self):
        calls = []
        self.start(lambda runtime: calls.append(runtime))
        status, html = self.request("GET", self.prefix)
        self.assertEqual(status, 200)
        self.assertIn('type="password"', html)
        for headers in ({"Origin": "https://attacker.invalid"}, {"X-GAG-Session": "wrong"}, {"Host": "attacker.invalid"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.save(headers=headers)[0], 403)
        self.assertEqual(self.request("POST", self.prefix + "api/save", '{}')[0], 403)
        for token in ("", " \t", "a\r\nb", TOKEN + "\n", "\r" + TOKEN, "a\0b", "a" * 4097):
            with self.subTest(token=repr(token[:10])):
                self.assertEqual(self.save(token)[0], 400)
        for body in ('{', '[]', '{"token":123}', '{}'):
            self.assertEqual(self.save(body=body)[0], 400)
        self.assertFalse((self.project / ".gag-dev-team/scripta-token").exists())
        self.assertEqual(calls, [])

    def test_double_save_starts_one_job_and_never_returns_token(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def slow(runtime):
            calls.append(runtime)
            entered.set()
            release.wait(3)
            return Path("/fake/graphify")
        self.start(slow)
        self.addCleanup(release.set)
        status, body = self.save()
        self.assertEqual(status, 202)
        self.assertNotIn(TOKEN, body)
        self.assertTrue(entered.wait(2))
        self.assertEqual(self.save()[0], 409)
        release.set()
        state = self.wait_state()
        self.assertIn("done", (state.get("state"), state.get("status")))
        self.assertNotIn(TOKEN, json.dumps(state))
        self.assertEqual(len(calls), 1)

    def test_graphify_failure_preserves_saved_key_and_hides_exception_secret(self):
        def fail(runtime):
            raise RuntimeError("dependency failure " + TOKEN)
        self.start(fail)
        self.assertEqual(self.save()[0], 202)
        state = self.wait_state()
        self.assertIn("error", (state.get("state"), state.get("status")))
        self.assertNotIn(TOKEN, json.dumps(state))
        self.assertEqual((self.project / ".gag-dev-team/scripta-token").read_text().strip(), TOKEN)






class AdditionalContracts(ProjectCase):
    def test_native_helper_outputs_only_header_json_and_fails_without_secret(self):
        runtime = self.install.install(self.project, source=ROOT)
        helper = runtime / "mcp/scripta_headers.py"
        missing = subprocess.run([sys.executable, str(helper)], capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(missing.stdout, "")
        self.install.configure_scripta(self.project, TOKEN)
        config = tomllib.loads((self.project / ".codex/config.toml").read_text())
        command = config["mcp_servers"]["docs"]["http_headers_helper"]
        result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self.project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"Authorization": "Bearer " + TOKEN})
        self.assertEqual(result.stderr, "")

    def test_preexisting_hooks_and_caveman_preferences_survive_install(self):
        hooks_path = self.project / ".codex/hooks.json"
        hooks_path.parent.mkdir()
        own_hook = {"matcher": "*", "hooks": [{"type": "command", "command": "echo custom"}]}
        hooks_path.write_text(json.dumps({"hooks": {"SessionStart": [own_hook]}}))
        (self.project / ".caveman.json").write_text('{"customPreference": true}')
        self.install.install(self.project, source=ROOT)
        hooks = json.loads(hooks_path.read_text())["hooks"]
        self.assertIn(own_hook, hooks["SessionStart"])
        self.assertTrue(json.loads((self.project / ".caveman.json").read_text())["customPreference"])

    def test_existing_unmanaged_docs_server_refuses_without_mutation(self):
        path = self.project / ".codex/config.toml"
        path.parent.mkdir()
        path.write_text('[mcp_servers.docs]\nurl = "https://custom.invalid/mcp"\n')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.install.install(self.project, source=ROOT)
        self.assertEqual(self.snapshot(), before)

    def test_previously_tracked_private_file_refuses_install(self):
        path = self.project / ".gag-dev-team/scripta-token"
        path.parent.mkdir()
        path.write_text("old-test-token")
        subprocess.run(["git", "add", ".gag-dev-team/scripta-token"], cwd=self.project, check=True)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.install.install(self.project, source=ROOT)
        self.assertEqual(self.snapshot(), before)


    def test_local_saved_token_is_used_by_scripta_access_hook(self):
        from unittest.mock import Mock
        runtime = self.install.install(self.project, source=ROOT)
        self.install.configure_scripta(self.project, TOKEN)
        spec = importlib.util.spec_from_file_location("qa_local_scripta", runtime / "hooks/scripts/check_scripta.py")
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        client = Mock()
        client.send.return_value = {"protocolVersion": "2025-03-26"}
        client.call.side_effect = [{"projects": [{"slug": "renew-it", "role": "editor"}]}, {"project": {"slug": "renew-it"}}]
        factory = Mock(return_value=client)
        self.assertEqual(check.inspect_access(runtime, factory), "ok")
        factory.assert_called_once_with("Bearer " + TOKEN)
        client.call.assert_any_call("docs_briefing", {"project": "renew-it"})

    def test_exact_token_limit_is_accepted_and_invalid_input_preserves_previous_key(self):
        self.install.install(self.project, source=ROOT)
        accepted = "a" * 4096
        self.install.configure_scripta(self.project, accepted)
        for token in ("", "a" * 4097, TOKEN + "\r", "\n" + TOKEN, "a\0b", None):
            with self.subTest(kind=type(token).__name__):
                with self.assertRaises(ValueError):
                    self.install.configure_scripta(self.project, token)
                self.assertEqual((self.project / ".gag-dev-team/scripta-token").read_text(), accepted)

    def test_project_session_hook_does_not_install_graphify_before_save(self):
        import contextlib
        import io
        from unittest.mock import patch
        runtime = self.install.install(self.project, source=ROOT)
        spec = importlib.util.spec_from_file_location("qa_local_graphify", runtime / "hooks/scripts/graphify_hook.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        output = io.StringIO()
        with patch.object(hook, "ensure_graphify") as ensure, patch.object(sys, "argv", ["graphify_hook.py", "session"]), patch.object(sys, "stdin", io.StringIO("{}")), contextlib.redirect_stdout(output):
            hook.main()
        ensure.assert_not_called()
        self.assertIn("configure", output.getvalue())

class HttpBoundsTests(HttpTests):
    # Keep the cases in HttpTests from running twice through inheritance.
    test_double_save_starts_one_job_and_never_returns_token = None
    test_graphify_failure_preserves_saved_key_and_hides_exception_secret = None
    test_page_and_rejected_requests_have_no_secret_side_effect = None

    def test_explicit_body_bounds_fixed_routes_and_session_are_enforced(self):
        calls = []
        self.start(lambda runtime: calls.append(runtime))
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertGreaterEqual(len(self.server.session), 32)
        self.assertEqual(self.save(body="x" * 8193)[0], 413)
        self.assertEqual(self.save(headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("GET", "/wrong/api/status")[0], 403)
        self.assertEqual(self.request("GET", self.prefix + "../scripts/gag_dev_team.py")[0], 404)
        for asset in ("configure.js", "configure.css"):
            self.assertEqual(self.request("GET", self.prefix + asset)[0], 200)
        self.assertFalse((self.project / ".gag-dev-team/scripta-token").exists())
        self.assertEqual(calls, [])

    def test_visible_page_and_completion_feedback_only_mention_scripta(self):
        def unavailable(runtime):
            raise RuntimeError("fake dependency unavailable")
        self.start(unavailable)
        status, html = self.request("GET", self.prefix)
        self.assertEqual(status, 200)
        self.assertIn("Scripta", html)
        self.assertIn("<img", html)
        self.assertIn("compartilh", html.lower())
        for forbidden in ("graphify", "gag"):
            self.assertNotIn(forbidden, html.lower())
        status, body = self.save()
        self.assertEqual(status, 202)
        state = self.wait_state()
        for payload in (json.loads(body), state):
            message = payload.get("message", "")
            self.assertIn("Scripta", message)
            for forbidden in ("graphify", "gag"):
                self.assertNotIn(forbidden, message.lower())

if __name__ == "__main__":
    unittest.main()
