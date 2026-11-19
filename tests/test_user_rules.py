"""Private rule storage and review evidence; semantic review belongs to the agent."""
import importlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import threading
import uuid
from unittest.mock import patch

from test_project_cli import ProjectCase, ROOT


class UserRulesCase(ProjectCase):
    def setUp(self):
        super().setUp()
        self.git("config", "user.name", "QA")
        self.git("config", "user.email", "qa@example.invalid")
        (self.project / "README.md").write_text("# Synthetic QA project\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "base")
        self.runtime = self.install.install(self.project, source=ROOT)
        self.rules = importlib.import_module("user_rules")
        self.marker = "QA_PRIVATE_" + uuid.uuid4().hex
        self.content = "Use concise Portuguese progress updates. Synthetic marker " + self.marker + "."

    def git(self, *arguments, cwd=None):
        return subprocess.check_output(["git", *arguments], cwd=cwd or self.project,
                                       stderr=subprocess.DEVNULL).decode().strip()

    def propose(self, content=None, project=None):
        return self.rules.propose_rule(project or self.project, content or self.content,
                                       plugin_root=self.runtime)

    def review(self, proposed, decision="accept", project=None, **changes):
        arguments = {
            "decision": decision, "reviewer": "Independent synthetic QA reviewer",
            "reason": "Synthetic review against the current plugin policies.",
            "expected_content_digest": proposed["rule"]["content_digest"],
            "expected_policy_digest": proposed["policy_digest"],
            "expected_revision": proposed["revision"], "plugin_root": self.runtime,
        }
        arguments.update(changes)
        return self.rules.review_rule(project or self.project, proposed["rule"]["id"], **arguments)

    def effective(self, project=None):
        return self.rules.effective_rules(project or self.project, plugin_root=self.runtime)

    def rule_storage(self, project=None):
        identity = importlib.import_module("environment_identity")
        binding = identity.project_binding(project or self.project, identity.resolve_identity())
        return Path(binding["runtime_root"]) / "rules"

    def immutable_bytes(self):
        root = self.rule_storage().parent.parent
        return {str(path.relative_to(root)): path.read_bytes()
                for directory in (root / "events", root / "versions")
                for path in directory.rglob("*") if path.is_file()}

    def record_file(self, rule_id):
        for path in self.rule_storage().rglob("*.json"):
            if rule_id in path.read_text(encoding="utf-8"):
                return path
        self.fail("No private JSON record contains the synthetic rule identifier")

    def edit_record(self, rule_id, **changes):
        path = self.record_file(rule_id)
        payload = json.loads(path.read_text(encoding="utf-8"))

        def update(value):
            if isinstance(value, dict):
                if value.get("id") == rule_id:
                    value.update(changes)
                    return True
                return any(update(child) for child in value.values())
            if isinstance(value, list):
                return any(update(child) for child in value)
            return False

        self.assertTrue(update(payload), "The synthetic record could not be located")
        path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")


class UserRuleStorageTests(UserRulesCase):
    def test_storage_is_inside_common_git_metadata_and_cannot_be_staged(self):
        proposed = self.propose()
        expected = Path(self.git("rev-parse", "--path-format=absolute", "--git-common-dir"))
        storage = self.rule_storage()
        binding = importlib.import_module("environment_identity").project_binding(
            self.project, importlib.import_module("environment_identity").resolve_identity())
        self.assertEqual(storage, Path(binding["runtime_root"]) / "rules")
        self.assertTrue(storage.is_relative_to(expected))
        self.assertFalse(storage.is_relative_to(self.project / ".gag-dev-team"))
        self.git("add", ".")
        self.assertNotIn(self.marker, self.git("diff", "--cached", "--binary"))
        subprocess.run(["git", "add", "-f", "--", str(self.record_file(proposed["rule"]["id"]))],
                       cwd=self.project, capture_output=True, text=True)
        # Git may reject metadata paths or accept them as a no-op; neither may stage the payload.
        self.assertNotIn(self.marker, self.git("diff", "--cached", "--binary"))
        private_prefix = storage.relative_to(self.project).as_posix() + "/"
        self.assertFalse(any(name.startswith(private_prefix) for name in self.git("ls-files").splitlines()))

    def test_linked_worktrees_share_rules_despite_git_file_and_spaces(self):
        proposed = self.propose()
        self.review(proposed)
        worktree = self.project.parent / ("linked worktree " + uuid.uuid4().hex)
        self.git("worktree", "add", "-qb", "qa-linked", str(worktree))
        self.addCleanup(lambda: subprocess.run(["git", "worktree", "remove", "--force", str(worktree)],
                                              cwd=self.project, capture_output=True))
        self.assertTrue((worktree / ".git").is_file())
        self.assertEqual(self.rules.storage_root(worktree), self.rules.storage_root(self.project))
        active = self.effective(worktree)
        self.assertEqual([item["content"] for item in active["rules"]], [self.content])
        nested = worktree / "nested folder"
        nested.mkdir()
        self.assertEqual(self.rules.storage_root(nested), self.rules.storage_root(self.project))

    def test_separate_git_directory_is_resolved_through_git(self):
        project = self.project.parent / ("separate project " + uuid.uuid4().hex)
        metadata = self.project.parent / ("separate metadata " + uuid.uuid4().hex)
        self.addCleanup(shutil.rmtree, project, True)
        self.addCleanup(shutil.rmtree, metadata, True)
        subprocess.run(["git", "init", "-q", "--separate-git-dir", str(metadata), str(project)], check=True)
        self.assertTrue((project / ".git").is_file())
        self.assertEqual(self.rules.storage_root(project), metadata / "gag-dev-team/user-rules")
        proposed = self.propose(project=project)
        self.assertEqual(proposed["rule"]["status"], "pending")

    def test_independent_clone_does_not_receive_private_rules(self):
        self.review(self.propose())
        clone = self.project.parent / ("independent clone " + uuid.uuid4().hex)
        self.addCleanup(shutil.rmtree, clone, True)
        subprocess.run(["git", "clone", "--quiet", "--local", str(self.project), str(clone)], check=True)
        self.assertEqual(self.effective(clone)["rules"], [])

    def test_private_records_are_not_world_readable(self):
        proposed = self.propose()
        path = self.record_file(proposed["rule"]["id"])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)

    def test_identical_shipped_policies_have_the_same_digest_after_installation(self):
        source = self.rules.policy_snapshot(ROOT)
        installed = self.rules.policy_snapshot(self.runtime)
        self.assertEqual(installed["policy_digest"], source["policy_digest"])
        self.assertTrue(installed["manifest"])
        self.assertNotIn(self.marker, json.dumps(installed))

    def test_versionable_metadata_directory_is_not_accepted_as_private_storage(self):
        project = self.project.parent / ("unsafe metadata project " + uuid.uuid4().hex)
        project.mkdir()
        self.addCleanup(shutil.rmtree, project, True)
        metadata = project / "ordinary_metadata"
        subprocess.run(["git", "init", "-q", "--separate-git-dir", str(metadata), str(project)], check=True)
        with self.assertRaises(self.rules.UserRulesError):
            self.propose(project=project)
        self.assertFalse((metadata / "gag-dev-team/user-rules").exists())

    def test_metadata_inside_another_worktree_is_not_private_storage(self):
        project = self.project.parent / ("external project " + uuid.uuid4().hex)
        project.mkdir()
        self.addCleanup(shutil.rmtree, project, True)
        metadata = self.project / "ordinary_external_metadata"
        subprocess.run(["git", "init", "-q", "--separate-git-dir", str(metadata), str(project)], check=True)
        with self.assertRaises(self.rules.UserRulesError):
            self.propose(project=project)
        self.assertFalse((metadata / "gag-dev-team/user-rules").exists())

    def test_git_environment_cannot_redirect_private_storage_to_another_project(self):
        expected = self.rules.storage_root(self.project)
        other = self.project.parent / ("other project " + uuid.uuid4().hex)
        other.mkdir()
        self.addCleanup(shutil.rmtree, other, True)
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        with patch.dict(os.environ, {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}):
            try:
                actual = self.rules.storage_root(self.project)
            except self.rules.UserRulesError:
                actual = None
        self.assertIn(actual, (None, expected))
        self.assertFalse((other / ".git/gag-dev-team/user-rules").exists())

    def test_symlinked_storage_parent_does_not_write_outside_metadata(self):
        outside = self.project.parent / ("outside storage " + uuid.uuid4().hex)
        outside.mkdir()
        self.addCleanup(shutil.rmtree, outside, True)
        metadata = Path(self.git("rev-parse", "--path-format=absolute", "--git-common-dir"))
        (metadata / "gag-dev-team").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(self.rules.UserRulesError):
            self.propose()
        self.assertEqual(list(outside.iterdir()), [])


class UserRuleReviewTests(UserRulesCase):
    def test_proposal_is_inactive_until_explicit_review_then_context_is_immediate(self):
        proposed = self.propose()
        self.assertEqual(proposed["rule"]["status"], "pending")
        self.assertEqual(self.effective()["rules"], [])
        accepted = self.review(proposed)
        self.assertEqual(accepted["rule"]["status"], "active")
        state = self.effective()
        self.assertEqual([item["content"] for item in state["rules"]], [self.content])
        context = self.rules.context_for(self.project, plugin_root=self.runtime)
        self.assertEqual(context["active_count"], 1)
        self.assertIn(self.content, context["context"])
        self.assertIn("plugin", context["context"].lower())
        self.assertEqual(context["policy_digest"], self.rules.policy_snapshot(self.runtime)["policy_digest"])

    def test_rejected_and_unclear_reviews_remain_inactive(self):
        for decision, status in (("reject", "rejected"), ("unclear", "unclear")):
            with self.subTest(decision=decision):
                proposed = self.propose(content="Synthetic review decision: " + decision)
                reviewed = self.review(proposed, decision=decision)
                self.assertEqual(reviewed["rule"]["status"], status)
                self.assertNotIn(proposed["rule"]["id"], [item["id"] for item in self.effective()["rules"]])

    def test_review_rejects_stale_revision_content_and_policy_evidence(self):
        proposed = self.propose()
        for changes in ({"expected_revision": proposed["revision"] - 1},
                        {"expected_content_digest": "0" * 64},
                        {"expected_policy_digest": "0" * 64}):
            with self.subTest(changes=changes), self.assertRaises(self.rules.UserRulesError):
                self.review(proposed, **changes)
        self.assertEqual(self.effective()["rules"], [])

    def test_missing_reviewer_or_reason_cannot_create_an_active_review(self):
        proposed = self.propose()
        for changes in ({"reviewer": ""}, {"reason": ""}):
            with self.subTest(changes=changes), self.assertRaises(self.rules.UserRulesError):
                self.review(proposed, **changes)
        self.assertEqual(self.effective()["rules"], [])

    def test_policy_change_suspends_review_without_deleting_private_text(self):
        proposed = self.propose()
        accepted = self.review(proposed)
        path = self.runtime / "skills/development-workflow/SKILL.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSynthetic QA policy change.\n", encoding="utf-8")
        current = self.effective()
        self.assertEqual(current["rules"], [])
        self.assertTrue(current["diagnostics"])
        stored = self.rules.read_rule(self.project, proposed["rule"]["id"], plugin_root=self.runtime)
        self.assertEqual(stored["rule"]["content"], self.content)
        self.assertFalse(stored["effective"])
        self.assertEqual(stored["revision"], accepted["revision"])
        path.write_bytes(b"\xff")
        invalid_policy = self.effective()
        self.assertEqual(invalid_policy["rules"], [])
        self.assertTrue(invalid_policy["diagnostics"])
        self.assertNotIn(self.content, self.rules.context_for(self.project, plugin_root=self.runtime)["context"])

    def test_manual_content_edit_invalidates_the_bound_review(self):
        proposed = self.propose()
        self.review(proposed)
        before = self.immutable_bytes()
        for replacement in ("Tampered synthetic private content " + uuid.uuid4().hex, "\ud800"):
            with self.subTest(replacement=repr(replacement)):
                self.edit_record(proposed["rule"]["id"], content=replacement)
                result = self.effective()
                self.assertEqual([item["content"] for item in result["rules"]], [self.content])
                context = self.rules.context_for(self.project, plugin_root=self.runtime)
                self.assertNotIn(replacement, context["context"])
                self.assertIn(self.content, context["context"])
                self.assertEqual(self.immutable_bytes(), before)

    def test_symlinked_registry_does_not_read_or_modify_an_external_file(self):
        proposed = self.propose()
        accepted = self.review(proposed)
        path = self.record_file(proposed["rule"]["id"])
        outside = self.project / "outside_registry.json"
        outside.write_bytes(path.read_bytes())
        before = outside.read_bytes()
        path.unlink()
        path.symlink_to(outside)
        effective = self.effective()
        self.assertEqual(effective["rules"], [])
        self.assertTrue(effective["diagnostics"])
        with self.assertRaises(self.rules.UserRulesError):
            self.rules.remove_rule(self.project, proposed["rule"]["id"],
                                   accepted["revision"],
                                   plugin_root=self.runtime)
        self.assertEqual(outside.read_bytes(), before)

    def test_status_flip_without_review_evidence_does_not_activate_rule(self):
        proposed = self.propose()
        self.edit_record(proposed["rule"]["id"], status="active")
        self.assertEqual(self.effective()["rules"], [])

    def test_remove_refreshes_effective_context_and_rejects_stale_writes(self):
        proposed = self.propose()
        accepted = self.review(proposed)
        with self.assertRaises(self.rules.UserRulesError):
            self.rules.remove_rule(self.project, proposed["rule"]["id"], proposed["revision"],
                                   plugin_root=self.runtime)
        removed = self.rules.remove_rule(self.project, proposed["rule"]["id"], accepted["revision"],
                                         plugin_root=self.runtime)
        self.assertTrue(removed["removed"])
        context = self.rules.context_for(self.project, plugin_root=self.runtime)
        self.assertEqual(context["active_count"], 0)
        self.assertNotIn(self.content, context["context"])
        self.assertGreater(context["revision"], accepted["revision"])

    def test_concurrent_proposals_do_not_overwrite_each_other(self):
        barrier = threading.Barrier(2)
        results, errors = [], []

        def propose(content):
            try:
                barrier.wait(timeout=3)
                results.append(self.propose(content=content))
            except Exception as error:
                errors.append(error)

        workers = [threading.Thread(target=propose, args=("Synthetic concurrent rule " + str(index),))
                   for index in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len({result["rule"]["id"] for result in results}), 2)
        listed = self.rules.list_rules(self.project, plugin_root=self.runtime)
        self.assertEqual(len(listed["rules"]), 2)
        self.assertEqual(sorted(result["revision"] for result in results), [1, 2])

    def test_reinstall_preserves_the_private_registry_and_its_active_rules(self):
        self.review(self.propose())
        before = {path.relative_to(self.rules.storage_root(self.project)): path.read_bytes()
                  for path in self.rules.storage_root(self.project).rglob("*") if path.is_file()}
        self.install.install(self.project, source=ROOT)
        after = {path.relative_to(self.rules.storage_root(self.project)): path.read_bytes()
                 for path in self.rules.storage_root(self.project).rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assertEqual([item["content"] for item in self.effective()["rules"]], [self.content])

    def test_corrupt_and_oversized_registry_never_become_effective_context(self):
        proposed = self.propose()
        self.review(proposed)
        before = self.immutable_bytes()
        path = self.record_file(proposed["rule"]["id"])
        for content in ("{", " " * (self.rules.MAX_STATE_BYTES + 1)):
            with self.subTest(size=len(content)):
                path.write_text(content, encoding="utf-8")
                effective = self.effective()
                self.assertEqual([item["content"] for item in effective["rules"]], [self.content])
                context = self.rules.context_for(self.project, plugin_root=self.runtime)
                self.assertIn(self.content, context["context"])
                self.assertEqual(self.immutable_bytes(), before)

    def test_rule_size_limit_counts_utf8_bytes_and_preserves_previous_state(self):
        valid = "é" * (self.rules.MAX_RULE_BYTES // 2)
        proposed = self.rules.propose_rule(self.project, valid, plugin_root=self.runtime)
        before = self.rules.list_rules(self.project, plugin_root=self.runtime)
        for invalid in ("", "\0", valid + "é"):
            with self.subTest(size=len(invalid.encode("utf-8"))), self.assertRaises(self.rules.UserRulesError):
                self.rules.propose_rule(self.project, invalid, plugin_root=self.runtime)
        after = self.rules.list_rules(self.project, plugin_root=self.runtime)
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual([item["id"] for item in after["rules"]], [proposed["rule"]["id"]])

    def test_effective_limit_disables_the_whole_set_instead_of_truncating_rules(self):
        content = ("Keep progress updates concise. " * self.rules.MAX_RULE_BYTES)[:self.rules.MAX_RULE_BYTES]
        count = self.rules.MAX_EFFECTIVE_BYTES // self.rules.MAX_RULE_BYTES + 1
        for _ in range(count):
            self.review(self.propose(content=content))
        effective = self.effective()
        self.assertEqual(effective["rules"], [])
        self.assertTrue(effective["diagnostics"])
        context = self.rules.context_for(self.project, plugin_root=self.runtime)
        self.assertEqual(context["active_count"], 0)
        self.assertNotIn(content, context["context"])

    def test_rule_identifier_cannot_escape_storage_or_read_arbitrary_files(self):
        outside = self.project / "outside.txt"
        outside.write_text(self.marker, encoding="utf-8")
        for rule_id in ("../outside.txt", str(outside), "..\\outside.txt", "bad\0identifier"):
            with self.subTest(rule_id=repr(rule_id)), self.assertRaises(self.rules.UserRulesError):
                self.rules.read_rule(self.project, rule_id, plugin_root=self.runtime)
        self.assertEqual(outside.read_text(encoding="utf-8"), self.marker)

    def test_rule_count_limit_preserves_every_existing_proposal(self):
        for index in range(self.rules.MAX_RULES):
            self.propose(content="Keep updates concise. Synthetic rule " + str(index))
        before = self.rules.list_rules(self.project, plugin_root=self.runtime)
        with self.assertRaises(self.rules.UserRulesError):
            self.propose()
        after = self.rules.list_rules(self.project, plugin_root=self.runtime)
        self.assertEqual(after, before)
        self.assertEqual(len(after["rules"]), self.rules.MAX_RULES)
