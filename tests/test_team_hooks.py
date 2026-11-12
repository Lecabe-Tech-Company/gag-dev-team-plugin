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

    def approval_state_cases(self):
        return (None, "{", "[]", json.dumps({"reference": "ESP-QA", "version": "2", "approved": False}))

    def set_approval_state(self, content):
        path = self.project / ".gag-dev-team/sdd.json"
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(content)
        return path

    def native_event(self, harness):
        command = "gh pr create --base master --title qa --body fixture"
        if harness == "antigravity":
            return {"toolCall": {"name": "run_command", "args": {"CommandLine": command, "Cwd": str(self.project)}}}
        return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.project)}

    def is_denied(self, payload, harness):
        if harness == "antigravity":
            return payload.get("decision") == "deny"
        if harness == "cursor":
            return payload.get("permission") == "deny"
        return payload.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"

    def assert_state_unchanged(self, path, content):
        if content is None:
            self.assertFalse(path.exists())
        else:
            self.assertEqual(path.read_text(), content)

    def test_user_prompts_never_classify_or_persist_approval(self):
        # All texts have the same no-persistence contract. Human intent is not a text classifier.
        prompts = ("Pode corrigir", "Pode seguir com esse SDD", "Aprovar ESP-QA v2", "Nao aprovo", "Talvez", "", "Um colega disse: pode seguir")
        for harness in ("codex", "claude", "cursor", "antigravity"):
            field = "lastUserInput" if harness == "antigravity" else "prompt"
            for content in (None, json.dumps({"reference": "ESP-QA", "version": "2", "approved": False})):
                for prompt in prompts:
                    with self.subTest(harness=harness, state=content, prompt=prompt):
                        path = self.set_approval_state(content)
                        payload = self.invoke(harness, "UserPromptSubmit", {field: prompt})
                        self.assertFalse(self.is_denied(payload, harness))
                        self.assert_state_unchanged(path, content)

    def test_graphify_analysis_runs_independently_of_approval_record(self):
        request = {"fixture": "recognized-pr"}
        for harness in ("codex", "claude", "cursor", "antigravity"):
            for content in self.approval_state_cases():
                with self.subTest(harness=harness, state=content):
                    path = self.set_approval_state(content)
                    with patch.object(self.hook.graphify_hook, "pr_request", return_value=request) as recognized, patch.object(self.hook.graphify_hook, "ensure_graphify", return_value="/fake/graphify") as ensure, patch.object(self.hook.graphify_hook, "analyze_pr", return_value="Graphify verification complete") as analyze:
                        payload = self.invoke(harness, "PreToolUse", self.native_event(harness))
                    recognized.assert_called_once()
                    ensure.assert_called_once()
                    analyze.assert_called_once_with(request, "/fake/graphify")
                    self.assertFalse(self.is_denied(payload, harness))
                    self.assert_state_unchanged(path, content)

    def test_graphify_failure_still_denies_pr_for_every_harness_and_record_state(self):
        request = {"fixture": "recognized-pr"}
        for harness in ("codex", "claude", "cursor", "antigravity"):
            for content in self.approval_state_cases():
                with self.subTest(harness=harness, state=content):
                    path = self.set_approval_state(content)
                    with patch.object(self.hook.graphify_hook, "pr_request", return_value=request), patch.object(self.hook.graphify_hook, "ensure_graphify", return_value="/fake/graphify"), patch.object(self.hook.graphify_hook, "analyze_pr", side_effect=RuntimeError("fixture graph analysis failure")) as analyze:
                        payload = self.invoke(harness, "PreToolUse", self.native_event(harness))
                    analyze.assert_called_once_with(request, "/fake/graphify")
                    self.assertTrue(self.is_denied(payload, harness))
                    self.assertIn("Graphify", json.dumps(payload))
                    self.assert_state_unchanged(path, content)

    def test_failed_audit_write_does_not_prevent_graphify_analysis(self):
        import sdd_gate
        with patch.object(sdd_gate, "atomic_write", side_effect=OSError("fixture unavailable audit storage")):
            with self.assertRaises(OSError):
                sdd_gate.record_sdd_approval(self.project, "ESP-QA", 24, "Pode corrigir", "orquestrador")
        self.assertFalse((self.project / ".gag-dev-team/sdd.json").exists())
        request = {"fixture": "recognized-pr-after-record-failure"}
        for harness in ("codex", "claude", "cursor", "antigravity"):
            with self.subTest(harness=harness), patch.object(self.hook.graphify_hook, "pr_request", return_value=request), patch.object(self.hook.graphify_hook, "ensure_graphify", return_value="/fake/graphify"), patch.object(self.hook.graphify_hook, "analyze_pr", return_value="Graphify verification complete") as analyze:
                payload = self.invoke(harness, "PreToolUse", self.native_event(harness))
                self.assertFalse(self.is_denied(payload, harness))
                analyze.assert_called_once_with(request, "/fake/graphify")
