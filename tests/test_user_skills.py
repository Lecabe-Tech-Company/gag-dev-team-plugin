"""Private skill bundles and evidence, independent of natural-language classification."""
import importlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import threading
import uuid

from test_user_rules import UserRulesCase


class UserSkillsCase(UserRulesCase):
    def setUp(self):
        super().setUp()
        self.skills = importlib.import_module("user_skills")
        self.body_marker = "QA_BODY_" + uuid.uuid4().hex
        self.reference_marker = "QA_REFERENCE_" + uuid.uuid4().hex
        self.bundle = self.make_bundle()

    def make_bundle(self, name="short-progress", source_kind="explicit"):
        description = "Use concise progress updates for this project"
        return {
            "name": name, "description": description,
            "skill_md": "---\nname: " + name + "\ndescription: " + description + "\n---\n\n"
                        "# Atualizações do trabalho\n\n"
                        "Use mensagens concisas em português e preserve as verificações do plugin.\n\n"
                        + self.body_marker + "\n",
            "references": {"references/interview-notes.md": "Aproveite respostas já fornecidas. "
                           + self.reference_marker + "\n"},
            "source_kind": source_kind,
            "origin": ("Synthetic explicit request in the current project task" if source_kind == "explicit"
                       else "Synthetic isolated observation in the current task"),
            "evidence": ("Synthetic person requested concise project progress updates" if source_kind == "explicit"
                         else "One synthetic clarification event, not a confirmed preference"),
            "applicability": "When providing progress updates for this project",
        }

    def propose_skill(self, bundle=None, project=None, **changes):
        return self.skills.propose_skill(project or self.project, bundle or self.bundle,
                                         plugin_root=self.runtime, **changes)

    def review_skill(self, proposed, decision="accept", **changes):
        arguments = {
            "decision": decision, "reviewer": "Independent synthetic QA reviewer",
            "reason": "Synthetic skill review preserves mandatory plugin policies.",
            "expected_content_digest": proposed["content_digest"],
            "expected_policy_digest": proposed["policy_digest"],
            "expected_revision": proposed["revision"], "plugin_root": self.runtime,
        }
        arguments.update(changes)
        return self.skills.review_skill(self.project, proposed["id"], **arguments)

    def catalog(self, project=None):
        return self.skills.catalog_for(project or self.project, plugin_root=self.runtime)

    def skill_storage(self, project=None):
        common = Path(self.git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=project))
        return common / "gag-dev-team/user-skills"

    def skill_file(self):
        for path in self.skill_storage().rglob("SKILL.md"):
            if self.body_marker in path.read_text(encoding="utf-8"):
                return path
        self.fail("No private SKILL.md contains the synthetic bundle")

    def skill_record_file(self, identifier):
        for path in self.skill_storage().rglob("*.json"):
            if identifier in path.read_text(encoding="utf-8"):
                return path
        self.fail("No private skill record contains the synthetic identifier")

    def edit_skill_record(self, identifier, **changes):
        path = self.skill_record_file(identifier)
        payload = json.loads(path.read_text(encoding="utf-8"))

        def update(value):
            if isinstance(value, dict):
                if value.get("id") == identifier:
                    value.update(changes)
                    return True
                return any(update(child) for child in value.values())
            if isinstance(value, list):
                return any(update(child) for child in value)
            return False

        self.assertTrue(update(payload))
        path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

    def assert_skill_inactive(self, identifier):
        catalog = self.catalog()
        self.assertNotIn(identifier, [item["id"] for item in catalog["skills"]])
        self.assertNotIn(self.body_marker, catalog["context"])
        try:
            loaded = self.skills.load_skill(self.project, identifier, plugin_root=self.runtime)
        except self.skills.UserSkillsError:
            return
        self.assertFalse(loaded.get("skill"))
        self.assertTrue(loaded["diagnostics"])
        self.assertNotIn(self.body_marker, loaded["context"])
        self.assertNotIn(self.reference_marker, loaded["context"])


class UserSkillBundleTests(UserSkillsCase):
    def test_private_bundle_has_a_namespace_and_cannot_be_staged(self):
        proposed = self.propose_skill()
        path = self.skill_file()
        self.assertTrue(path.is_relative_to(self.skill_storage()))
        self.assertEqual(path.read_text(encoding="utf-8"), self.bundle["skill_md"])
        self.assertEqual((path.parent / "references/interview-notes.md").read_text(encoding="utf-8"),
                         self.bundle["references"]["references/interview-notes.md"])
        self.git("add", ".")
        subprocess.run(["git", "add", "-f", "--", str(path)], cwd=self.project,
                       capture_output=True, text=True)
        staged = self.git("diff", "--cached", "--binary")
        self.assertNotIn(self.body_marker, staged)
        self.assertNotIn(self.reference_marker, staged)
        private_prefix = self.skill_storage().relative_to(self.project).as_posix() + "/"
        self.assertFalse(any(name.startswith(private_prefix) for name in self.git("ls-files").splitlines()))
        self.assertEqual(proposed["slug"], self.bundle["name"])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)

    def test_name_and_frontmatter_are_validated_before_storage(self):
        cases = []
        for name in ("../outside", "/absolute", "C:\\outside", "Uppercase", "bad_name"):
            cases.append(self.make_bundle(name=name))
        mismatch = self.make_bundle()
        mismatch["skill_md"] = mismatch["skill_md"].replace("name: short-progress", "name: other-progress")
        cases.append(mismatch)
        missing = self.make_bundle()
        missing["skill_md"] = "# No frontmatter\n"
        cases.append(missing)
        extra = self.make_bundle()
        extra["skill_md"] = extra["skill_md"].replace("---\n\n#", "unexpected: true\n---\n\n#")
        cases.append(extra)
        for bundle in cases:
            with self.subTest(name=bundle["name"], header=bundle["skill_md"][:50]), self.assertRaises(self.skills.UserSkillsError):
                self.propose_skill(bundle)
        self.assertEqual(self.skills.list_skills(self.project, plugin_root=self.runtime)["skills"], [])

    def test_references_are_text_only_and_cannot_escape_the_bundle(self):
        for name, content in (("../outside.md", "data"), ("references/../../outside.md", "data"),
                              ("C:\\outside.txt", "data"), ("/outside.md", "data"),
                              ("references/run.py", "raise RuntimeError('must not run')"),
                              ("references/data.md", {"not": "text"}),
                              ("references/data.md", "\ud800")):
            bundle = self.make_bundle()
            bundle["references"] = {name: content}
            with self.subTest(name=name), self.assertRaises(self.skills.UserSkillsError):
                self.propose_skill(bundle)
        self.assertEqual(self.skills.list_skills(self.project, plugin_root=self.runtime)["skills"], [])

    def test_skill_text_is_declarative_and_never_executed(self):
        target = self.project / "must_not_execute.txt"
        bundle = self.make_bundle()
        bundle["skill_md"] += "\n__import__('pathlib').Path(" + repr(str(target)) + ").write_text('executed')\n"
        proposed = self.propose_skill(bundle)
        self.review_skill(proposed)
        self.skills.load_skill(self.project, proposed["id"], plugin_root=self.runtime)
        self.assertFalse(target.exists())

    def test_private_namespace_does_not_overwrite_distributed_skills(self):
        public = self.runtime / "skills/manage-user-rules/SKILL.md"
        original = public.read_bytes()
        try:
            proposed = self.propose_skill(self.make_bundle(name="manage-user-rules"))
        except self.skills.UserSkillsError:
            proposed = None
        if proposed:
            self.review_skill(proposed)
            catalog = self.catalog()
            entry = next(item for item in catalog["skills"] if item["id"] == proposed["id"])
            self.assertEqual(entry["namespace"], "user/manage-user-rules")
        self.assertEqual(public.read_bytes(), original)

    def test_reference_and_bundle_limits_reject_without_partial_catalog_entries(self):
        excessive = self.make_bundle()
        excessive["references"] = {"references/note-" + str(index) + ".md": "Synthetic text"
                                    for index in range(self.skills.MAX_REFERENCES + 1)}
        oversized_reference = self.make_bundle()
        oversized_reference["references"] = {"references/large-note.txt": "é" * (self.skills.MAX_REFERENCE_BYTES // 2 + 1)}
        oversized_bundle = self.make_bundle()
        oversized_bundle["skill_md"] += "x" * self.skills.MAX_BUNDLE_BYTES
        for bundle in (excessive, oversized_reference, oversized_bundle):
            with self.subTest(reference_count=len(bundle["references"])), self.assertRaises(self.skills.UserSkillsError):
                self.propose_skill(bundle)
        self.assertEqual(self.skills.list_skills(self.project, plugin_root=self.runtime)["skills"], [])
        valid = self.make_bundle()
        valid["references"] = {"references/large-note.txt": "é" * (self.skills.MAX_REFERENCE_BYTES // 2)}
        proposed = self.propose_skill(valid)
        self.assertEqual(proposed["status"], "pending")

    def test_symlinked_private_storage_cannot_redirect_bundle_writes(self):
        outside = self.project / "outside_private_skills"
        outside.mkdir()
        storage = self.skill_storage()
        storage.parent.mkdir(parents=True, exist_ok=True)
        storage.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(self.skills.UserSkillsError):
            self.propose_skill()
        self.assertEqual(list(outside.iterdir()), [])

    def test_skill_metadata_inside_another_worktree_is_not_private_storage(self):
        project = self.project.parent / ("external skill project " + uuid.uuid4().hex)
        project.mkdir()
        self.addCleanup(shutil.rmtree, project, True)
        metadata = self.project / "ordinary_external_metadata"
        subprocess.run(["git", "init", "-q", "--separate-git-dir", str(metadata), str(project)], check=True)
        with self.assertRaises(self.skills.UserSkillsError):
            self.propose_skill(project=project)
        self.assertFalse((metadata / "gag-dev-team/user-skills").exists())


class UserSkillReviewTests(UserSkillsCase):
    def test_only_reviewed_metadata_is_cataloged_and_content_loads_on_demand(self):
        proposed = self.propose_skill()
        self.assertNotEqual(proposed["status"], "active")
        self.assertEqual(self.catalog()["skills"], [])
        self.review_skill(proposed)
        catalog = self.catalog()
        self.assertEqual(len(catalog["skills"]), 1)
        self.assertEqual(catalog["skills"][0]["namespace"], "user/short-progress")
        self.assertNotIn(self.body_marker, json.dumps(catalog, ensure_ascii=False))
        self.assertNotIn(self.reference_marker, json.dumps(catalog, ensure_ascii=False))
        loaded = self.skills.load_skill(self.project, proposed["id"], plugin_root=self.runtime)
        self.assertEqual(loaded["skill"]["skill_md"], self.bundle["skill_md"])
        self.assertEqual(loaded["skill"]["references"], self.bundle["references"])
        self.assertIn(self.body_marker, loaded["context"])
        self.assertIn(self.reference_marker, loaded["context"])
        self.assertIn("plugin", loaded["context"].casefold())
        self.assertIn(loaded["policy_digest"], loaded["context"])

    def test_inferred_observation_cannot_activate_without_user_clarification(self):
        proposed = self.propose_skill(self.make_bundle(source_kind="inferred"))
        try:
            self.review_skill(proposed)
        except self.skills.UserSkillsError:
            pass
        self.assert_skill_inactive(proposed["id"])
        listed = self.skills.list_skills(self.project, plugin_root=self.runtime)
        record = self.skills.read_skill(self.project, proposed["id"], plugin_root=self.runtime)["skill"]
        confirmed = self.skills.confirm_skill_origin(
            self.project, proposed["id"], "Synthetic person confirms concise project progress updates.",
            expected_content_digest=record["content_digest"], expected_policy_digest=listed["policy_digest"],
            expected_revision=listed["revision"], plugin_root=self.runtime,
        )
        self.assertEqual(confirmed["status"], "pending")
        self.assertEqual(confirmed["source_kind"], "explicit")
        self.assertNotEqual(confirmed["content_digest"], proposed["content_digest"])
        self.assertEqual(self.catalog()["skills"], [])
        self.review_skill(confirmed)
        self.assertEqual([item["id"] for item in self.catalog()["skills"]], [proposed["id"]])

    def test_rejected_and_unclear_skill_reviews_stay_out_of_the_catalog(self):
        for decision in ("reject", "unclear"):
            with self.subTest(decision=decision):
                proposed = self.propose_skill(self.make_bundle(name="progress-" + decision))
                self.review_skill(proposed, decision=decision)
                self.assert_skill_inactive(proposed["id"])

    def test_review_checks_revision_content_and_policy_evidence(self):
        proposed = self.propose_skill()
        for changes in ({"expected_revision": proposed["revision"] - 1},
                        {"expected_content_digest": "0" * 64}, {"expected_policy_digest": "0" * 64}):
            with self.subTest(changes=changes), self.assertRaises(self.skills.UserSkillsError):
                self.review_skill(proposed, **changes)
        self.assertEqual(self.catalog()["skills"], [])

    def test_policy_changes_suspend_skills_without_deleting_the_bundle(self):
        proposed = self.propose_skill()
        self.review_skill(proposed)
        path = self.runtime / "skills/development-workflow/SKILL.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSynthetic policy revision.\n", encoding="utf-8")
        self.assert_skill_inactive(proposed["id"])
        self.assertTrue(self.catalog()["diagnostics"])
        self.assertEqual(self.skill_file().read_text(encoding="utf-8"), self.bundle["skill_md"])

    def test_review_integrity_covers_body_references_and_provenance(self):
        proposed = self.propose_skill()
        self.review_skill(proposed)
        body = self.skill_file()
        for path in (body, body.parent / "references/interview-notes.md"):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"\nTampered synthetic data.\n")
                self.assert_skill_inactive(proposed["id"])
                path.write_bytes(original)
        self.edit_skill_record(proposed["id"], origin="Tampered synthetic provenance")
        self.assert_skill_inactive(proposed["id"])

    def test_symlinked_reference_is_inactive_even_when_external_bytes_match(self):
        proposed = self.propose_skill()
        self.review_skill(proposed)
        reference = self.skill_file().parent / "references/interview-notes.md"
        original = reference.read_bytes()
        outside = self.project / "external_reference.md"
        outside.write_bytes(original)
        reference.unlink()
        reference.symlink_to(outside)
        self.assert_skill_inactive(proposed["id"])
        self.assertEqual(outside.read_bytes(), original)

    def test_unmanifested_files_or_scripts_invalidate_the_whole_bundle(self):
        proposed = self.propose_skill()
        self.review_skill(proposed)
        folder = self.skill_file().parent
        for relative in ("references/extra-note.md", "scripts/run.sh", "references/extra-link.md"):
            with self.subTest(path=relative):
                path = folder / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if relative.endswith("extra-link.md"):
                    path.symlink_to(folder / "references/interview-notes.md")
                else:
                    path.write_text("Synthetic unreviewed content.\n", encoding="utf-8")
                self.assert_skill_inactive(proposed["id"])
                path.unlink()
                if path.parent.name == "scripts":
                    path.parent.rmdir()

    def test_removal_replaces_the_catalog_and_invalidates_on_demand_loading(self):
        proposed = self.propose_skill()
        reviewed = self.review_skill(proposed)
        with self.assertRaises(self.skills.UserSkillsError):
            self.skills.remove_skill(self.project, proposed["id"], proposed["revision"], plugin_root=self.runtime)
        removed = self.skills.remove_skill(self.project, proposed["id"], reviewed["revision"], plugin_root=self.runtime)
        self.assertTrue(removed["removed"])
        catalog = self.catalog()
        self.assertEqual(catalog["skills"], [])
        self.assertNotIn("user/short-progress", catalog["context"])
        self.assert_skill_inactive(proposed["id"])

    def test_linked_worktrees_share_the_private_skill_catalog(self):
        proposed = self.propose_skill()
        self.review_skill(proposed)
        worktree = self.project.parent / ("skill worktree " + uuid.uuid4().hex)
        self.git("worktree", "add", "-qb", "qa-skill-linked", str(worktree))
        self.addCleanup(lambda: subprocess.run(["git", "worktree", "remove", "--force", str(worktree)],
                                              cwd=self.project, capture_output=True))
        self.assertTrue((worktree / ".git").is_file())
        self.assertEqual([item["id"] for item in self.catalog(worktree)["skills"]], [proposed["id"]])

    def test_concurrent_skill_proposals_do_not_replace_each_other(self):
        barrier = threading.Barrier(2)
        results, errors = [], []

        def propose(name):
            try:
                barrier.wait(timeout=3)
                results.append(self.propose_skill(self.make_bundle(name=name)))
            except Exception as error:
                errors.append(error)

        workers = [threading.Thread(target=propose, args=("progress-" + str(index),)) for index in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len({result["id"] for result in results}), 2)
        self.assertEqual(sorted(result["revision"] for result in results), [1, 2])
        self.assertEqual(len(self.skills.list_skills(self.project, plugin_root=self.runtime)["skills"]), 2)

    def test_invalid_identifiers_cannot_load_files_outside_private_storage(self):
        for identifier in ("../outside", "/outside", "C:\\outside", "bad\0identifier"):
            with self.subTest(identifier=repr(identifier)), self.assertRaises(self.skills.UserSkillsError):
                self.skills.read_skill(self.project, identifier, plugin_root=self.runtime)

    def test_catalog_limit_disables_the_set_without_partial_entries_or_body_leaks(self):
        for index in range(self.skills.MAX_SKILLS):
            bundle = self.make_bundle(name="progress-" + str(index))
            description = ("Synthetic concise progress guidance " * 8).strip()
            bundle["skill_md"] = bundle["skill_md"].replace(bundle["description"], description)
            bundle["description"] = description
            bundle["applicability"] = ("When providing a progress update for this project. " * 8).strip()
            self.review_skill(self.propose_skill(bundle))
        catalog = self.catalog()
        self.assertEqual(catalog["skills"], [])
        self.assertTrue(catalog["diagnostics"])
        self.assertNotIn(self.body_marker, catalog["context"])
        self.assertLessEqual(len(catalog["context"].encode("utf-8")), self.skills.MAX_CATALOG_BYTES)
