"""Explicit ownership, preservation, and account boundaries for v0.4 data."""
import importlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from environment_fixtures import EnvironmentCase


class LegacyImportTests(EnvironmentCase):
    def setUp(self):
        super().setUp()
        self.legacy = importlib.import_module("legacy_import")
        self.rules = importlib.import_module("user_rules")
        self.skills = importlib.import_module("user_skills")
        self.confirmation = {"ownership_confirmed": True,
                             "evidence": "These existing project rules and skills are mine; associate them with my authenticated account.",
                             "recorded_by": "Independent synthetic QA"}
        seed_identity = self.resolve_fake_identity(999, "qa-seed")
        seed_binding = self.identity_module.project_binding(self.project, seed_identity)
        with patch.object(self.identity_module, "resolve_identity", return_value=seed_identity):
            self.rules.propose_rule(self.project, "Synthetic legacy preference: keep concise updates.")
            bundle = {"name": "legacy-interview", "description": "Ask focused project questions",
                      "skill_md": "---\nname: legacy-interview\ndescription: Ask focused project questions\n---\n\n# Interview\nUse existing answers before asking a question.\n",
                      "references": {"references/question-guide.md": "Ask for missing acceptance criteria.\n"},
                      "source_kind": "explicit", "origin": "Synthetic user request", "evidence": "The synthetic user requested focused interviews.",
                      "applicability": "When planning this synthetic project"}
            self.skills.propose_skill(self.project, bundle)
        rule_directory, rule_path, _lock = self.rules._paths(self.project, binding=seed_binding)
        skill_directory, skill_path, _lock = self.skills._state_paths(self.project, binding=seed_binding)
        self.rule_state = json.loads(rule_path.read_text())
        self.skill_state = json.loads(skill_path.read_text())
        self.rule_record = self.rule_state["rules"][0]
        self.skill_record = self.skill_state["skills"][0]
        for record in (self.rule_record, self.skill_record):
            record["status"] = "active"
            record["review"] = {"decision": "accept", "reviewer": "Synthetic legacy reviewer", "reason": "Synthetic historical review.",
                                "content_digest": record["content_digest"], "policy_digest": "0" * 64,
                                "reviewed_at": "2025-01-01T00:00:00+00:00"}
        self.legacy_rule_root = self.rules.private_storage_root(self.project, "user-rules")
        self.legacy_skill_root = self.rules.private_storage_root(self.project, "user-skills")
        self.legacy_rule_root.mkdir(parents=True)
        self.legacy_skill_root.mkdir(parents=True)
        (self.legacy_rule_root / "state.json").write_bytes(json.dumps(self.rule_state, indent=3).encode() + b"\n")
        (self.legacy_skill_root / "catalog.json").write_bytes(json.dumps(self.skill_state, indent=3).encode() + b"\n")
        source = skill_directory / self.skill_record["slug"] / self.skill_record["id"]
        shutil.copytree(source, self.legacy_skill_root / self.skill_record["slug"])

    def legacy_bytes(self):
        return {str(path.relative_to(root.parent)): path.read_bytes()
                for root in (self.legacy_rule_root, self.legacy_skill_root)
                for path in root.rglob("*") if path.is_file()}

    def claim(self, confirmation=None):
        with patch.object(self.identity_module, "resolve_identity", return_value=self.identity):
            return self.legacy.claim_legacy(self.binding, self.confirmation if confirmation is None else confirmation)

    def test_unclaimed_legacy_is_not_attributed_and_missing_confirmation_writes_nothing(self):
        original = self.legacy_bytes()
        before = self.history_bytes()
        self.assertEqual(self.projection.read_snapshot(self.binding)["rules"], [])
        self.assertEqual(self.projection.read_snapshot(self.binding)["skills"], [])
        for confirmation in ({}, {"ownership_confirmed": False, "evidence": "Not mine", "recorded_by": "QA"},
                             {"ownership_confirmed": True, "recorded_by": "QA"}):
            with self.subTest(confirmation=confirmation), self.assertRaises(self.legacy.LegacyImportError):
                self.claim(confirmation)
        self.assertEqual(self.history_bytes(), before)
        self.assertEqual(self.legacy_bytes(), original)

    def test_explicit_claim_preserves_every_source_byte_and_retry_is_idempotent(self):
        original = self.legacy_bytes()
        result = self.claim()
        self.assertTrue(result["imported"])
        self.assertEqual((result["rules"], result["skills"]), (1, 1))
        before_retry = self.history_bytes()
        retry = self.claim()
        self.assertFalse(retry["imported"])
        self.assertEqual(self.history_bytes(), before_retry)
        self.assertEqual(self.legacy_bytes(), original)
        retained = list(self.history_bytes().values())
        for content in original.values():
            self.assertIn(content, retained)

    def test_import_does_not_reactivate_stale_reviews_or_share_with_another_account(self):
        self.claim()
        snapshot = self.projection.read_snapshot(self.binding)
        self.assertEqual([item["status"] for item in snapshot["rules"]], ["inactive"])
        self.assertEqual([item["status"] for item in snapshot["skills"]], ["inactive"])
        with patch.object(self.identity_module, "resolve_identity", return_value=self.identity):
            self.assertEqual(self.rules.effective_rules(self.project)["rules"], [])
            self.assertEqual(self.skills.catalog_for(self.project)["skills"], [])
        second = self.binding_for(202, "qa-second")
        self.assertEqual(self.projection.read_snapshot(second)["rules"], [])
        self.assertEqual(self.projection.read_snapshot(second)["skills"], [])

    def test_account_switch_during_claim_cannot_write_imported_content_into_another_account_cache(self):
        second_identity = self.resolve_fake_identity(202, "qa-second")
        second = self.identity_module.project_binding(self.project, second_identity)
        with patch.object(self.identity_module, "resolve_identity", return_value=second_identity):
            try:
                self.legacy.claim_legacy(self.binding, self.confirmation)
            except self.legacy.LegacyImportError:
                pass
            listing = self.rules.list_rules(self.project)
            catalog = self.skills.list_skills(self.project)
        self.assertEqual(listing["rules"], [])
        self.assertEqual(catalog["skills"], [])
        private_bytes = b"".join(path.read_bytes() for path in Path(second["private_root"]).rglob("*") if path.is_file())
        self.assertNotIn(self.rule_record["content"].encode(), private_bytes)

    def test_legacy_bundle_symlink_is_refused_without_reading_external_content(self):
        external = self.fake_home / "external.md"
        external.write_text("Synthetic external private material.")
        target = self.legacy_skill_root / self.skill_record["slug"] / "references/external.md"
        target.symlink_to(external)
        original = self.legacy_bytes()
        with self.assertRaises(self.legacy.LegacyImportError):
            self.claim()
        self.assertEqual(self.legacy_bytes(), original)
        self.assertNotIn(external.read_bytes(), self.history_bytes().values())
