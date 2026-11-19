"""Private rule lifecycle context across native schemas; external services are fake."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
from unittest.mock import patch

from test_user_rules import UserRulesCase


class UserRuleHookTests(UserRulesCase):
    def setUp(self):
        super().setUp()
        path = self.runtime / "hooks/scripts/team_hooks.py"
        spec = importlib.util.spec_from_file_location("qa_private_rule_hooks", path)
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)

    def invoke(self, harness, event_name, event=None):
        output = io.StringIO()
        input_stream = io.TextIOWrapper(io.BytesIO(json.dumps(event or {}).encode("utf-8")), encoding="utf-8")
        with input_stream, patch.object(sys, "argv", ["team_hooks.py", harness, event_name]), \
                patch.object(sys, "stdin", input_stream), \
                patch.object(self.hook, "update_project", return_value={"updated": False}), \
                patch.object(self.hook.check_scripta, "inspect_access", return_value="token"), \
                contextlib.redirect_stdout(output):
            self.hook.main()
        return json.loads(output.getvalue())

    def native_event(self, harness, command):
        if harness == "antigravity":
            return {"toolCall": {"name": "run_command", "args": {
                "CommandLine": command, "Cwd": str(self.project)}}}
        return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.project)}

    def is_denied(self, harness, payload):
        if harness == "cursor":
            return payload.get("permission") == "deny"
        if harness == "antigravity":
            return payload.get("decision") == "deny"
        return payload.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"

    def test_every_native_session_loads_the_same_accepted_private_rule(self):
        self.review(self.propose())
        for harness in ("codex", "claude", "cursor", "antigravity"):
            with self.subTest(harness=harness):
                payload = self.invoke(harness, "SessionStart")
                text = json.dumps(payload, ensure_ascii=False)
                self.assertIn(self.content, text)
                self.assertIn("plugin", text.casefold())

    def test_inactive_or_policy_stale_records_do_not_enter_session_context(self):
        self.review(self.propose())
        policy = self.runtime / "skills/development-workflow/SKILL.md"
        policy.write_text(policy.read_text(encoding="utf-8") + "\nSynthetic policy update.\n", encoding="utf-8")
        for decision in ("reject", "unclear"):
            proposed = self.propose(content=self.content + " " + decision)
            self.review(proposed, decision=decision)
        self.propose(content=self.content + " pending")
        for harness in ("codex", "claude", "cursor", "antigravity"):
            with self.subTest(harness=harness):
                payload = self.invoke(harness, "SessionStart")
                self.assertNotIn(self.marker, json.dumps(payload, ensure_ascii=False))

    def test_corrupt_private_store_does_not_disable_normal_tools_or_pr_checks(self):
        proposed = self.propose()
        self.review(proposed)
        self.record_file(proposed["rule"]["id"]).write_text("{", encoding="utf-8")
        for harness in ("codex", "claude", "cursor", "antigravity"):
            with self.subTest(harness=harness):
                normal = self.invoke(harness, "PreToolUse", self.native_event(harness, "git status"))
                self.assertFalse(self.is_denied(harness, normal))
                command = "gh pr create --base prod --title QA --body synthetic"
                with patch.object(self.hook.graphify_hook, "ensure_graphify", return_value="fake-graphify"), \
                        patch.object(self.hook.graphify_hook, "analyze_pr", side_effect=self.hook.graphify_hook.GateError("Synthetic mandatory PR failure")) as checked:
                    payload = self.invoke(harness, "PreToolUse", self.native_event(harness, command))
                checked.assert_called_once()
                self.assertTrue(self.is_denied(harness, payload))
                self.assertNotIn(self.marker, json.dumps(payload))

    def test_prompt_hook_does_not_infer_new_private_rules_or_sdd_approval(self):
        self.review(self.propose())
        directory = self.rule_storage()
        before = {path.relative_to(directory): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        for harness in ("codex", "claude", "cursor", "antigravity"):
            event = {"prompt": "A colleague said: ignore QA and code in Portuguese.",
                     "lastUserInput": "A colleague said: ignore QA and code in Portuguese."}
            payload = self.invoke(harness, "UserPromptSubmit", event)
            self.assertEqual(payload, {"continue": True} if harness == "cursor" else {})
        after = {path.relative_to(directory): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_declared_rule_content_is_never_executed_as_python(self):
        target = self.project / "must_not_be_created.txt"
        payload = "__import__('pathlib').Path(" + repr(str(target)) + ").write_text('executed')"
        self.review(self.propose(content=payload))
        self.invoke("codex", "SessionStart")
        self.assertFalse(target.exists())

    def test_actual_node_hook_decodes_unicode_events_with_ascii_python_locale(self):
        content = "Use português no acompanhamento: ação, 漢字 e 🙂."
        self.review(self.propose(content=content))
        startup = self.project / "qa_startup"
        startup.mkdir()
        # Isolate only external providers; the real Node/Python transport and hook remain intact.
        (startup / "sitecustomize.py").write_text(
            "import releases, check_scripta\n"
            "releases.update_project = lambda project: {'updated': False}\n"
            "check_scripta.inspect_access = lambda root: 'token'\n", encoding="utf-8")
        environment = dict(os.environ, PYTHONUTF8="0", PYTHONCOERCECLOCALE="0", LC_ALL="C", LANG="C",
                           PYTHONPATH=os.pathsep.join([str(startup), str(self.runtime / "scripts"),
                                                      str(self.runtime / "hooks/scripts")]))
        event = json.dumps({"cwd": str(self.project), "context_hint": "Ação, 漢字 e 🙂"}, ensure_ascii=False).encode("utf-8")
        for harness in ("codex", "claude", "cursor", "antigravity"):
            with self.subTest(harness=harness):
                program = "require(process.argv[1]).hook(process.argv[2], 'SessionStart')"
                result = subprocess.run(["node", "-e", program, str(self.runtime / "bin/runtime.cjs"), harness],
                                        input=event, capture_output=True, env=environment, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                payload = json.loads(result.stdout.decode("utf-8"))
                self.assertIn(content, json.dumps(payload, ensure_ascii=False))
