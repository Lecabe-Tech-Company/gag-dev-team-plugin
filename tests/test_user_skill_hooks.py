"""Native discovery advertises reviewed private skill metadata, never full bundles."""
import importlib.util
import json

import test_user_rule_hooks as rule_hooks
from test_user_skills import UserSkillsCase


class UserSkillHookTests(UserSkillsCase):
    invoke = rule_hooks.UserRuleHookTests.invoke
    native_event = rule_hooks.UserRuleHookTests.native_event
    is_denied = rule_hooks.UserRuleHookTests.is_denied

    def setUp(self):
        super().setUp()
        path = self.runtime / "hooks/scripts/team_hooks.py"
        spec = importlib.util.spec_from_file_location("qa_private_skill_hooks", path)
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)

    def test_every_native_session_receives_metadata_without_body_or_reference_text(self):
        proposed = self.propose_skill()
        self.review_skill(proposed)
        digest = self.catalog()["policy_digest"]
        for harness in ("codex", "claude", "cursor", "antigravity"):
            with self.subTest(harness=harness):
                rendered = json.dumps(self.invoke(harness, "SessionStart"), ensure_ascii=False)
                self.assertIn("user/short-progress", rendered)
                self.assertIn(proposed["id"], rendered)
                self.assertIn(digest, rendered)
                self.assertNotIn(self.body_marker, rendered)
                self.assertNotIn(self.reference_marker, rendered)

    def test_corrupt_skill_catalog_warns_without_breaking_plugin_context(self):
        proposed = self.propose_skill()
        self.review_skill(proposed)
        self.skill_record_file(proposed["id"]).write_text("{", encoding="utf-8")
        expected = self.catalog()
        self.assertTrue(expected["diagnostics"])
        for harness in ("codex", "claude", "cursor", "antigravity"):
            with self.subTest(harness=harness):
                rendered = json.dumps(self.invoke(harness, "SessionStart"), ensure_ascii=False)
                self.assertIn("plugin", rendered.casefold())
                for diagnostic in expected["diagnostics"]:
                    reason = diagnostic["reason"] if isinstance(diagnostic, dict) else diagnostic
                    self.assertIn(reason, rendered)
                self.assertNotIn(self.body_marker, rendered)
                self.assertNotIn(self.reference_marker, rendered)

    def test_prompt_text_never_silently_confirms_an_inferred_skill(self):
        proposed = self.propose_skill(self.make_bundle(source_kind="inferred"))
        directory = self.skill_storage()
        before = {path.relative_to(directory): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        for harness in ("codex", "claude", "cursor", "antigravity"):
            event = {"prompt": "I observed a clarification; do not invent a permanent preference.",
                     "lastUserInput": "I observed a clarification; do not invent a permanent preference."}
            result = self.invoke(harness, "UserPromptSubmit", event)
            self.assertEqual(result, {"continue": True} if harness == "cursor" else {})
        after = {path.relative_to(directory): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assert_skill_inactive(proposed["id"])

    def test_removed_skill_disappears_from_the_next_native_catalog_snapshot(self):
        proposed = self.propose_skill()
        accepted = self.review_skill(proposed)
        self.assertIn("user/short-progress", json.dumps(self.invoke("codex", "SessionStart")))
        self.skills.remove_skill(self.project, proposed["id"], accepted["revision"], plugin_root=self.runtime)
        for harness in ("codex", "claude", "cursor", "antigravity"):
            with self.subTest(harness=harness):
                rendered = json.dumps(self.invoke(harness, "SessionStart"), ensure_ascii=False)
                self.assertNotIn("user/short-progress", rendered)
                self.assertNotIn(self.body_marker, rendered)
