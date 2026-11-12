"""Regressões do acesso e das orientações; sem rede ou credenciais reais."""
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("scripta_check", ROOT / "hooks/scripts/check_scripta.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {"mcpServers": {"docs": {
            "type": "streamable-http", "url": check.ENDPOINT,
            "headers": {"Authorization": "Bearer test-only-not-a-real-token"},
        }}}
        self.client = Mock()
        self.client.send.return_value = {"protocolVersion": "2025-03-26"}
        self.factory = Mock(return_value=self.client)

    def run_check(self, projects=None, briefing=None):
        (self.root / "mcp.json").write_text(json.dumps(self.config), encoding="utf-8")
        self.client.call.side_effect = [
            projects if projects is not None else {"projects": [{"slug": "renew-it", "role": "editor"}]},
            briefing if briefing is not None else {"project": {"slug": "renew-it"}},
        ]
        return check.inspect_access(self.root, self.factory)

    def test_placeholder_does_not_send_network_request(self):
        self.config["mcpServers"]["docs"]["headers"]["Authorization"] = "Bearer ds_gere_um_token_acima"
        self.assertEqual(self.run_check(), "token")
        self.factory.assert_not_called()

    def test_missing_config(self):
        self.assertEqual(check.inspect_access(self.root, self.factory), "config")

    def test_refuses_credentials_to_another_endpoint(self):
        self.config["mcpServers"]["docs"]["url"] = "https://other.example/mcp"
        self.assertEqual(self.run_check(), "config")
        self.factory.assert_not_called()

    def test_editor_can_read_projects_and_briefing(self):
        self.assertEqual(self.run_check(), "ok")
        self.assertEqual(self.client.call.call_count, 2)
        self.client.call.assert_any_call("docs_briefing", {"project": "renew-it"})

    def test_project_not_shared(self):
        self.assertEqual(self.run_check({"projects": []}), "project")

    def test_viewer_and_unknown_roles_cannot_be_reported_as_ready(self):
        for role in ["viewer", None, "unexpected"]:
            with self.subTest(role=role):
                self.assertEqual(self.run_check({"projects": [{"slug": "renew-it", "role": role}]}), "readonly")

    def test_wrong_briefing_is_not_a_success(self):
        self.assertEqual(self.run_check(briefing={"project": {"slug": "other"}}), "protocol")

    def test_errors_are_not_reported_as_success(self):
        for kind in ["auth", "permission", "network", "tool"]:
            self.client.send.side_effect = check.CheckError(kind)
            self.assertEqual(self.run_check(), kind)

    def test_guidance_includes_original_excerpt_and_no_credentials(self):
        output = check.output_for("project")
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("## 3. Solicitando acesso", context)
        self.assertIn("responsável pela documentação", context)
        self.assertNotIn("test-only-not-a-real-token", json.dumps(output))
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "SessionStart")


class WireTests(unittest.TestCase):
    def setUp(self):
        self.client = check.Client("Bearer test-only-not-a-real-token")
        self.client.opener = Mock()

    def response(self, payload, content_type="application/json"):
        response = io.BytesIO(payload)
        response.headers = {"Content-Type": content_type, "Mcp-Session-Id": "test-session"}
        return response

    def test_json_response_and_session_header(self):
        self.client.opener.open.return_value = self.response(b'{"jsonrpc":"2.0","id":1,"result":{}}')
        self.assertEqual(self.client.send("initialize"), {})
        self.assertEqual(self.client.session, "test-session")

    def test_sse_response_with_notification_before_result(self):
        self.client.opener.open.return_value = self.response(
            b'data: {"jsonrpc":"2.0","method":"notifications/message"}\n\n'
            b'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n',
            "text/event-stream",
        )
        self.assertEqual(self.client.send("initialize"), {"ok": True})

    def test_401_403_and_network_failure(self):
        for code, kind in [(401, "auth"), (403, "permission"), (503, "network")]:
            self.client.opener.open.side_effect = urllib.error.HTTPError(check.ENDPOINT, code, "", {}, None)
            with self.assertRaises(check.CheckError) as raised:
                self.client.send("initialize")
            self.assertEqual(raised.exception.kind, kind)

    def test_text_tool_result_with_scripta_preamble(self):
        self.client.send = Mock(return_value={"content": [
            {"type": "text", "text": 'Orientação do Scripta.\n{"projects":[]}'}
        ]})
        self.assertEqual(self.client.call("docs_list_projects", {}), {"projects": []})

    def test_tool_error_cannot_be_success(self):
        self.client.send = Mock(return_value={"isError": True, "content": []})
        with self.assertRaises(check.CheckError):
            self.client.call("docs_list_projects", {})


if __name__ == "__main__":
    unittest.main()
