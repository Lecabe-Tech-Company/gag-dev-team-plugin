"""Lifecycle hooks use fake update/access providers; never contact external services."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

from test_project_cli import ProjectCase, ROOT


class LifecycleTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.runtime = self.install.install(self.project, source=ROOT)
        spec = importlib.util.spec_from_file_location("qa_team_hooks", self.runtime / "hooks/scripts/team_hooks.py")
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)

    def invoke(self, harness, event_name, data):
        output = io.StringIO()
        with patch.object(sys, "argv", ["team_hooks.py", harness, event_name]), patch.object(sys, "stdin", io.StringIO(json.dumps(data))), contextlib.redirect_stdout(output):
            self.hook.main()
        return json.loads(output.getvalue())

    def test_start_and_stop_check_updates_without_reopening_stop(self):
        with patch.object(self.hook, "update_project", return_value={"updated": False}) as update, patch.object(self.hook.check_scripta, "inspect_access", return_value="token"), patch.object(self.hook.graphify_hook, "ensure_graphify") as graphify:
            start = self.invoke("codex", "SessionStart", {})
            self.assertIn("Orquestrador", json.dumps(start, ensure_ascii=False))
            self.assertEqual(update.call_count, 1)
            graphify.assert_not_called()
            stop = self.invoke("codex", "Stop", {})
            self.assertEqual(stop, {})
            self.assertEqual(update.call_count, 2)

    def test_update_network_failure_does_not_break_stop_or_reopen_turn(self):
        with patch.object(self.hook, "update_project", side_effect=OSError("offline fixture")) as update:
            self.assertEqual(self.invoke("claude", "Stop", {}), {})
            update.assert_called_once_with(self.project)

    def test_antigravity_active_parallel_tasks_skip_update(self):
        with patch.object(self.hook, "update_project") as update:
            self.assertEqual(self.invoke("antigravity", "Stop", {"fullyIdle": False}), {"decision": "stop"})
            update.assert_not_called()

    def test_native_user_prompts_unlock_only_the_current_declared_sdd(self):
        import sdd_gate
        cases = [("codex", "prompt"), ("claude", "prompt"), ("cursor", "prompt"), ("antigravity", "lastUserInput")]
        for version, (harness, field) in enumerate(cases, 1):
            with self.subTest(harness=harness):
                sdd_gate.declare_sdd(self.project, "ESP-QA", version)
                edit = {"tool_name": "Edit", "tool_input": {"file_path": "app.py"}}
                if harness == "antigravity":
                    edit = {"toolCall": {"name": "replace_file_content", "args": {"TargetFile": "app.py"}}}
                denied = self.invoke(harness, "PreToolUse", edit)
                self.assertIn("deny", json.dumps(denied))
                result = self.invoke(harness, "UserPromptSubmit", {field: "Aprovar ESP-QA v" + str(version)})
                self.assertEqual(result, {"continue": True} if harness == "cursor" else {})
                self.assertEqual(self.invoke(harness, "PreToolUse", edit), {})
                sdd_gate.declare_sdd(self.project, "ESP-QA", version + 1)
                self.invoke(harness, "UserPromptSubmit", {field: "Aprovar ESP-QA v" + str(version)})
                self.assertIn("deny", json.dumps(self.invoke(harness, "PreToolUse", edit)))
