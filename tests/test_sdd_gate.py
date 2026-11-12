"""ESP-071: optional contextual evidence is an audit record, not a tool gate."""
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
EVIDENCE = "Pode corrigir o SDD que voce acabou de apresentar."
RECORDER = "gag-orquestrador-planejador"


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gag contextual qa ")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.gate = importlib.import_module("sdd_gate")

    def state_path(self):
        return self.project / ".gag-dev-team/sdd.json"

    def state(self):
        return self.state_path().read_bytes()

    def record(self, reference=REFERENCE, version=24, evidence=EVIDENCE, recorded_by=RECORDER):
        return self.gate.record_sdd_approval(self.project, reference, version, evidence, recorded_by)

    def test_contextual_record_keeps_user_evidence_identity_and_recording_actor(self):
        state = self.record()
        self.assertIs(state["approved"], True)
        self.assertEqual(state["reference"], REFERENCE)
        self.assertEqual(state["version"], "24")
        self.assertEqual(state["evidence"], EVIDENCE)
        self.assertEqual(state["recorded_by"], RECORDER)
        self.assertEqual(state["approved_by"], "user")
        self.assertEqual(json.loads(self.state()), state)
        ignored = subprocess.run(["git", "check-ignore", "-q", "--", ".gag-dev-team/sdd.json"], cwd=self.project)
        self.assertEqual(ignored.returncode, 0)

    def test_record_before_declaration_is_preserved_for_same_identity(self):
        self.record()
        before = self.state()
        declared = self.gate.declare_sdd(self.project, REFERENCE, "24")
        self.assertIs(declared["approved"], True)
        self.assertEqual(self.state(), before)

    def test_record_after_declaration_is_supported(self):
        self.gate.declare_sdd(self.project, REFERENCE, 24)
        state = self.record()
        self.assertIs(state["approved"], True)
        self.assertEqual(state["evidence"], EVIDENCE)

    def test_new_explicit_record_can_precede_new_declaration_despite_old_identity(self):
        self.record(version=23, evidence="Pode seguir com a versao anterior.")
        old = json.loads(self.state())
        old["approved_at"] = "old-version-timestamp"
        self.state_path().write_text(json.dumps(old))
        state = self.record(version=24)
        self.assertNotIn("approved_at", state)
        self.assertEqual(state["version"], "24")
        self.assertEqual(state["evidence"], EVIDENCE)
        before = self.state()
        self.gate.declare_sdd(self.project, REFERENCE, 24)
        self.assertEqual(self.state(), before)
        other_reference = REFERENCE + "-another-feature"
        other_evidence = "Pode corrigir esse outro SDD apresentado."
        other = self.record(reference=other_reference, version=1, evidence=other_evidence)
        self.assertEqual(other["reference"], other_reference)
        self.assertEqual(other["version"], "1")
        self.assertEqual(other["evidence"], other_evidence)
        before = self.state()
        self.gate.declare_sdd(self.project, other_reference, 1)
        self.assertEqual(self.state(), before)

    def test_new_declaration_does_not_inherit_approval_or_current_evidence(self):
        self.record()
        changed = self.gate.declare_sdd(self.project, REFERENCE, 25)
        self.assertFalse(changed.get("approved", False))
        self.assertNotEqual(changed.get("evidence"), EVIDENCE)
        self.record(version=25)
        changed_reference = self.gate.declare_sdd(self.project, REFERENCE + "-other", 25)
        self.assertFalse(changed_reference.get("approved", False))
        self.assertNotEqual(changed_reference.get("evidence"), EVIDENCE)

    def test_invalid_evidence_or_recorder_cannot_replace_existing_audit_record(self):
        self.record()
        before = self.state()
        for evidence, actor in (("", RECORDER), ("  ", RECORDER), (None, RECORDER), (17, RECORDER), (EVIDENCE, ""), (EVIDENCE, " "), (EVIDENCE, None), (EVIDENCE, 17)):
            with self.subTest(evidence=evidence, actor=actor):
                with self.assertRaises(ValueError):
                    self.record(version=25, evidence=evidence, recorded_by=actor)
                self.assertEqual(self.state(), before)

    def test_invalid_identity_is_rejected_without_creating_state(self):
        for reference, version in (("", 1), (REFERENCE, 0), (REFERENCE, -1), (REFERENCE, None), (REFERENCE, True)):
            with self.subTest(reference=reference, version=version):
                with self.assertRaises(ValueError):
                    self.gate.declare_sdd(self.project, reference, version)
                with self.assertRaises(ValueError):
                    self.record(reference=reference, version=version)
                self.assertFalse(self.state_path().exists())

    def test_compatibility_gate_never_denies_or_writes_for_any_record_state(self):
        path = self.state_path()
        path.parent.mkdir()
        states = (None, "{", "[]", json.dumps({"reference": REFERENCE, "version": "24", "approved": False}), json.dumps({"approved": True}))
        events = ({"tool_name": "Edit", "tool_input": {"file_path": "app.py"}},
                  {"tool_name": "Bash", "tool_input": {"command": "python3 scripts/build.py"}},
                  {"tool_name": "Bash", "tool_input": {"command": "git diff --output=app.py"}},
                  {"toolName": "Write", "toolInput": {"file_path": "app.py"}},
                  {"toolCall": {"name": "replace_file_content", "args": {"TargetFile": "app.py"}}})
        for content in states:
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(content)
            for harness in ("codex", "claude", "cursor", "antigravity"):
                for event in events:
                    with self.subTest(harness=harness, state=content, event=event):
                        self.assertEqual(self.gate.gate(event, self.project, harness=harness), {})
                        if content is None:
                            self.assertFalse(path.exists())
                        else:
                            self.assertEqual(path.read_text(), content)

    def test_legacy_prompt_function_is_non_classifying_and_never_records(self):
        self.gate.declare_sdd(self.project, REFERENCE, 24)
        before = self.state()
        for prompt in ("Aprovar " + REFERENCE + " v24", "Pode corrigir", "Nao", "Talvez", ""):
            with self.subTest(prompt=prompt):
                self.assertFalse(self.gate.record_user_approval(self.project, prompt))
                self.assertEqual(self.state(), before)

    def test_explicit_manual_approval_alias_remains_usable_for_declared_identity(self):
        self.gate.declare_sdd(self.project, REFERENCE, 24)
        state = self.gate.approve_sdd(self.project, REFERENCE, 24, explicit=True)
        self.assertIs(state["approved"], True)
        self.assertEqual(state["reference"], REFERENCE)
        self.assertEqual(state["version"], "24")


    def test_manual_terminal_confirmation_before_declaration_does_not_invent_user_quote(self):
        state = self.gate.approve_sdd(self.project, REFERENCE, 24, explicit=True)
        self.assertIs(state["approved"], True)
        self.assertEqual(state["reference"], REFERENCE)
        self.assertEqual(state["version"], "24")
        self.assertEqual(state["approved_by"], "user")
        self.assertEqual(state["recorded_by"], "terminal")
        self.assertEqual(state["approval_source"], "terminal-confirmation")
        self.assertNotIn("evidence", state)
        before = self.state()
        self.gate.declare_sdd(self.project, REFERENCE, 24)
        self.assertEqual(self.state(), before)

    def test_evidence_is_saved_verbatim_without_parsing_or_whitespace_normalization(self):
        evidence = "  Pode corrigir o SDD apresentado.\nA citacao anterior 'nao aprove outro escopo' pertence a outro assunto.\t "
        state = self.record(evidence=evidence)
        self.assertEqual(state["evidence"], evidence)
        self.assertEqual(json.loads(self.state())["evidence"], evidence)

if __name__ == "__main__":
    unittest.main()
