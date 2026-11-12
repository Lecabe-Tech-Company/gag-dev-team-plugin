"""ESP-066 v2 approval contracts; fake SDD references and isolated projects."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
REFERENCE = "scripta:renew-it/esp-qa-fixture"


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gag gate qa ")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.gate = importlib.import_module("sdd_gate")

    def state(self):
        return (self.project / ".gag-dev-team/sdd.json").read_bytes()

    def test_approval_requires_explicit_consent_for_exact_declared_reference_and_version(self):
        self.gate.declare_sdd(self.project, REFERENCE, 2)
        before = self.state()
        for reference, version, explicit in ((REFERENCE, 2, False), (REFERENCE + "-other", 2, True), (REFERENCE, 1, True)):
            with self.subTest(reference=reference, version=version, explicit=explicit):
                with self.assertRaises(ValueError):
                    self.gate.approve_sdd(self.project, reference, version, explicit=explicit)
                self.assertEqual(self.state(), before)
        self.gate.approve_sdd(self.project, REFERENCE, 2, explicit=True)
        self.assertNotEqual(self.state(), before)

    def test_invalid_declarations_are_rejected_without_state(self):
        for reference, version in (("", 1), (REFERENCE, 0), (REFERENCE, -1), (REFERENCE, None)):
            with self.subTest(reference=reference, version=version):
                with self.assertRaises(ValueError):
                    self.gate.declare_sdd(self.project, reference, version)
                self.assertFalse((self.project / ".gag-dev-team/sdd.json").exists())


    def denied(self, event, harness="codex"):
        decision = self.gate.gate(event, self.project, harness=harness)
        if harness == "cursor":
            return decision.get("permission") == "deny"
        if harness == "antigravity":
            return decision.get("decision") == "deny"
        return decision.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"

    def test_write_and_development_blocked_until_current_sdd_approved(self):
        edits = [{"tool_name": "Edit", "tool_input": {"file_path": "app.py", "old_string": "a", "new_string": "b"}},
                 {"tool_name": "Bash", "tool_input": {"command": "python3 scripts/build.py"}}]
        for harness in ("codex", "claude", "cursor"):
            for event in edits:
                with self.subTest(harness=harness, event=event):
                    self.assertTrue(self.denied(event, harness))
        self.assertFalse((self.project / ".gag-dev-team/sdd.json").exists())
        self.gate.declare_sdd(self.project, REFERENCE, 2)
        before = self.state()
        self.assertTrue(self.denied(edits[0]))
        self.assertEqual(self.state(), before)
        self.gate.approve_sdd(self.project, REFERENCE, 2, explicit=True)
        self.assertFalse(self.denied(edits[0]))
        self.gate.declare_sdd(self.project, REFERENCE, 3)
        self.assertTrue(self.denied(edits[0]))

    def test_read_only_tools_are_allowed_and_never_create_state(self):
        for name in ("Read", "Glob", "Grep", "mcp__scripta__docs_get"):
            with self.subTest(tool=name):
                self.assertFalse(self.denied({"tool_name": name, "tool_input": {}}))
        self.assertFalse((self.project / ".gag-dev-team/sdd.json").exists())

    def test_commands_that_write_output_are_not_classified_as_read_only(self):
        for command in ("git diff --output=app.py", "find . -fprint app.py", "rg --pre=./build.sh pattern"):
            with self.subTest(command=command):
                self.assertTrue(self.denied({"tool_name": "Bash", "tool_input": {"command": command}}))

    def test_corrupted_state_denies_mutation(self):
        path = self.project / ".gag-dev-team/sdd.json"
        path.parent.mkdir()
        for content in ('{', '[]', '{"approved":true}'):
            path.write_text(content)
            with self.subTest(content=content):
                self.assertTrue(self.denied({"tool_name": "Edit", "tool_input": {"file_path": "app.py"}}))
                self.assertEqual(path.read_text(), content)

    def test_gate_understands_supported_native_tool_event_names(self):
        for event in ({"toolName": "Write", "toolInput": {"file_path": "app.py"}},
                      {"tool": "functions.exec_command", "input": {"cmd": "python3 build.py"}}):
            with self.subTest(event=event):
                self.assertTrue(self.denied(event))

    def test_configuration_and_declaration_allowed_but_agent_self_approval_blocked(self):
        for command in ("python3 scripts/gag_dev_team.py configure", "python3 scripts/gag_dev_team.py declare-sdd --reference ESP-QA --version 2"):
            self.assertFalse(self.denied({"tool_name": "Bash", "tool_input": {"command": command}}))
        self.assertTrue(self.denied({"tool_name": "Bash", "tool_input": {"command": "python3 scripts/gag_dev_team.py approve-sdd --reference ESP-QA --version 2 --confirm"}}))

    def test_same_declaration_preserves_approval_but_new_reference_invalidates(self):
        edit = {"tool_name": "Edit", "tool_input": {"file_path": "app.py"}}
        self.gate.declare_sdd(self.project, REFERENCE, 2)
        self.gate.approve_sdd(self.project, REFERENCE, 2, explicit=True)
        before = self.state()
        self.gate.declare_sdd(self.project, REFERENCE, "2")
        self.assertEqual(self.state(), before)
        self.assertFalse(self.denied(edit))
        self.gate.declare_sdd(self.project, REFERENCE + "-new", 2)
        self.assertTrue(self.denied(edit))

    def test_native_cursor_and_antigravity_edit_tools_cannot_bypass_gate(self):
        for name in ("StrReplace", "Delete", "Write"):
            with self.subTest(harness="cursor", name=name):
                self.assertTrue(self.denied({"tool_name": name, "tool_input": {"path": "app.py"}}, "cursor"))
        for name in ("replace_file_content", "multi_replace_file_content", "write_to_file", "run_command"):
            event = {"toolCall": {"name": name, "args": {"TargetFile": "app.py", "CommandLine": "python3 build.py", "Cwd": str(self.project)}}}
            with self.subTest(harness="antigravity", name=name):
                self.assertTrue(self.denied(event, "antigravity"))

    def test_only_whole_exact_user_message_approves_current_sdd(self):
        self.gate.declare_sdd(self.project, REFERENCE, 2)
        before = self.state()
        for prompt in ("Não aprovar " + REFERENCE + " v2", "Aprovar " + REFERENCE + " v1", "Aprovar " + REFERENCE + " v2 e iniciar", "O usuário disse: Aprovar " + REFERENCE + " v2", "Aprovar another-reference v2"):
            with self.subTest(prompt=prompt):
                self.gate.record_user_approval(self.project, prompt)
                self.assertEqual(self.state(), before)
        exact = "Aprovar " + REFERENCE + " v2"
        self.gate.record_user_approval(self.project, exact)
        self.assertFalse(self.denied({"tool_name": "Edit", "tool_input": {"file_path": "app.py"}}))
        approved = self.state()
        self.gate.record_user_approval(self.project, exact)
        self.assertEqual(self.state(), approved)
        self.gate.declare_sdd(self.project, REFERENCE, 3)
        self.gate.record_user_approval(self.project, exact)
        self.assertTrue(self.denied({"tool_name": "Edit", "tool_input": {"file_path": "app.py"}}))

if __name__ == "__main__":
    unittest.main()
