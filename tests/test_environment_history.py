"""Account isolation, immutable history, and honest model projections."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from environment_fixtures import EnvironmentCase
from test_project_cli import ROOT


class EnvironmentIdentityTests(EnvironmentCase):
    def test_numeric_account_and_host_isolate_data_while_login_rename_preserves_history(self):
        self.event_store.append_event(self.binding, {"event_type": "issue.opened", "issue_id": "first-issue", "summary": "Synthetic first account issue."}, "first-event")
        before = self.history_bytes()
        renamed = self.binding_for(101, "qa-renamed")
        self.assertEqual(renamed["private_root"], self.binding["private_root"])
        self.assert_history_preserved(before)
        self.assertEqual(self.projection.read_snapshot(renamed)["issues"][0]["id"], "first-issue")
        self.assertTrue(any(event["event_type"] == "identity.observed" and event["user"]["login"] == "qa-renamed"
                            for event in self.projection.read_snapshot(renamed)["events"]))
        second = self.binding_for(202, "qa-second")
        enterprise = self.identity_module.project_binding(self.project, self.resolve_fake_identity(101, "qa-first", "git.example.invalid"))
        self.assertNotEqual(second["private_root"], self.binding["private_root"])
        self.assertNotEqual(enterprise["private_root"], self.binding["private_root"])
        self.assertEqual(self.projection.read_snapshot(second)["issues"], [])
        self.assertEqual(self.projection.read_snapshot(enterprise)["issues"], [])
        self.git("add", ".")
        self.assertNotIn("Synthetic first account issue", self.git("diff", "--cached", "--binary"))

    def test_missing_or_malformed_authenticated_identity_does_not_fall_back_to_git_author(self):
        for response in ({}, {"id": True, "login": "qa-first"}, {"id": 0, "login": "qa-first"}, {"id": 101, "login": "../account"}):
            with self.subTest(response=response):
                def runner(command, **_options):
                    return subprocess.CompletedProcess(command, 0, stdout=json.dumps(response).encode(), stderr=b"")
                with self.assertRaises(self.identity_module.EnvironmentIdentityError):
                    self.identity_module.resolve_identity(runner=runner)

    def test_linked_worktrees_share_only_the_same_account_history(self):
        worktree = self.project.parent / (self.project.name + "-linked")
        self.git("worktree", "add", "-qb", "qa-environment-linked", str(worktree))
        self.addCleanup(lambda: subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=self.project, capture_output=True))
        linked = self.identity_module.project_binding(worktree, self.identity)
        self.assertEqual(linked["private_root"], self.binding["private_root"])
        self.assertEqual(linked["project_id"], self.binding["project_id"])
        other_account = self.binding_for(202, "qa-second", worktree)
        self.assertNotEqual(other_account["private_root"], linked["private_root"])

    def test_separate_git_metadata_inside_versionable_ancestor_is_rejected(self):
        outer = self.fake_home / "outer"
        metadata = outer / "tracked-metadata"
        nested = self.fake_home / "nested"
        subprocess.run(["git", "init", "-q", str(outer)], check=True)
        subprocess.run(["git", "init", "-q", "--separate-git-dir", str(metadata), str(nested)], check=True)
        with self.assertRaises(self.identity_module.EnvironmentIdentityError):
            self.identity_module.project_binding(nested, self.identity)

    def test_symlinked_account_directory_cannot_redirect_writes(self):
        account = Path(self.binding["account_root"])
        shutil.rmtree(account)
        destination = self.fake_home / "outside"
        destination.mkdir()
        account.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(self.identity_module.EnvironmentIdentityError):
            self.identity_module.project_binding(self.project, self.identity)
        self.assertEqual(list(destination.iterdir()), [])


class ImmutableHistoryTests(EnvironmentCase):
    def create_personal_context(self):
        rules = importlib.import_module("user_rules")
        skills = importlib.import_module("user_skills")
        rule = rules.propose_rule(self.project, "Keep synthetic progress updates concise.")
        bundle = {"name": "focused-interview", "description": "Ask focused project questions",
                  "skill_md": "---\nname: focused-interview\ndescription: Ask focused project questions\n---\n\n# Interview\nAsk for missing acceptance criteria.\n",
                  "references": {}, "source_kind": "explicit", "origin": "Synthetic explicit request",
                  "evidence": "The synthetic user requested focused questions.", "applicability": "When planning this project"}
        skill = skills.propose_skill(self.project, bundle)
        return rules, skills, rule, skill

    def test_rule_and_skill_review_and_deactivation_preserve_all_original_versions(self):
        with patch.object(self.identity_module, "resolve_identity", return_value=self.identity):
            rules, skills, rule, skill = self.create_personal_context()
            created = self.history_bytes()
            rule_review = rules.review_rule(self.project, rule["rule"]["id"], "accept", "Synthetic QA", "Compatible synthetic preference.",
                                            rule["rule"]["content_digest"], rule["policy_digest"], rule["revision"])
            skill_review = skills.review_skill(self.project, skill["id"], "accept", "Synthetic QA", "Compatible synthetic skill.",
                                                skill["content_digest"], skill["policy_digest"], skill["revision"])
            self.assert_history_preserved(created)
            reviewed = self.history_bytes()
            rules.remove_rule(self.project, rule["rule"]["id"], rule_review["revision"])
            skills.remove_skill(self.project, skill["id"], skill_review["revision"])
            self.assertEqual(rules.effective_rules(self.project)["rules"], [])
            self.assertEqual(skills.catalog_for(self.project)["skills"], [])
        self.assert_history_preserved(reviewed)
        snapshot = self.projection.read_snapshot(self.binding)
        self.assertEqual(snapshot["rules"][0]["status"], "inactive")
        self.assertEqual(snapshot["skills"][0]["status"], "inactive")
        self.assertEqual(len([event for event in snapshot["events"] if event["event_type"].startswith("rule.")]), 3)
        self.assertEqual(len([event for event in snapshot["events"] if event["event_type"].startswith("skill.")]), 3)

    def test_missing_runtime_catalogs_recover_from_history_instead_of_forgetting_context(self):
        with patch.object(self.identity_module, "resolve_identity", return_value=self.identity):
            rules, skills, rule, skill = self.create_personal_context()
            before = self.history_bytes()
            _directory, rule_cache, _lock = rules._paths(self.project, binding=self.binding)
            _directory, skill_cache, _lock = skills._state_paths(self.project, binding=self.binding)
            rule_cache.unlink()
            skill_cache.unlink()
            rule_listing = rules.list_rules(self.project)
            skill_listing = skills.list_skills(self.project)
        self.assertEqual([item["id"] for item in rule_listing["rules"]], [rule["rule"]["id"]])
        self.assertEqual([item["id"] for item in skill_listing["skills"]], [skill["id"]])
        self.assert_history_preserved(before)

    def test_retry_preserves_original_bytes_and_conflicting_content_cannot_overwrite(self):
        payload = {"event_type": "issue.opened", "issue_id": "retry-issue", "summary": "A synthetic operation failed."}
        first = self.event_store.append_event(self.binding, payload, "retry-event")
        before = self.history_bytes()
        second = self.event_store.append_event(self.binding, payload, "retry-event")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["event"], second["event"])
        with self.assertRaises(self.event_store.EventConflictError):
            self.event_store.append_event(self.binding, {**payload, "summary": "Different content."}, "retry-event")
        self.assertEqual(self.history_bytes(), before)

    def test_explicitly_changed_timestamp_is_not_the_same_idempotent_payload(self):
        payload = {"event_type": "attempt.recorded", "attempt_id": "dated-attempt", "recorded_at": "2026-01-01T10:00:00+00:00"}
        self.event_store.append_event(self.binding, payload, "dated-event")
        before = self.history_bytes()
        with self.assertRaises(self.event_store.EventConflictError):
            self.event_store.append_event(self.binding, {**payload, "recorded_at": "2026-01-01T11:00:00+00:00"}, "dated-event")
        self.assertEqual(self.history_bytes(), before)

    def test_time_filters_compare_instants_instead_of_iso_text_with_different_offsets(self):
        self.event_store.append_event(self.binding, {"event_type": "attempt.recorded", "attempt_id": "before-midnight", "recorded_at": "2026-01-01T02:00:00+03:00"}, "before-midnight-event")
        self.event_store.append_event(self.binding, {"event_type": "attempt.recorded", "attempt_id": "after-midnight", "recorded_at": "2026-01-01T00:15:00+00:00"}, "after-midnight-event")
        snapshot = self.projection.read_snapshot(self.binding, {"event_type": "attempt.recorded", "from": "2026-01-01T00:00:00+00:00"})
        self.assertEqual([event["attempt_id"] for event in snapshot["events"]], ["after-midnight"])
        self.assertEqual(sum(row["attempt_count"] for row in snapshot["models"]), 1)

    def test_process_writers_converge_without_lost_or_duplicate_events(self):
        code = ("import json,sys;sys.path.insert(0,sys.argv[1]);from event_store import append_event;"
                "binding=json.load(sys.stdin);worker=sys.argv[2];"
                "results=[append_event(binding,{'event_type':'attempt.recorded','attempt_id':'attempt-'+str(index)},'shared-'+str(index)) for index in range(6)];"
                "append_event(binding,{'event_type':'session.started','session_id':'session-'+worker},'worker-'+worker);"
                "print(sum(item['created'] for item in results))")
        workers = [subprocess.Popen([sys.executable, "-c", code, str(ROOT / "scripts"), str(index)],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for index in range(4)]
        for worker in workers:
            worker.stdin.write(json.dumps(self.binding).encode())
            worker.stdin.close()
            worker.stdin = None
        totals = []
        for worker in workers:
            output, errors = worker.communicate(timeout=30)
            self.assertEqual(worker.returncode, 0, errors.decode())
            totals.append(int(output))
        self.assertEqual(sum(totals), 6)
        events = self.projection.read_snapshot(self.binding)["events"]
        self.assertEqual(len([event for event in events if event["event_type"] == "attempt.recorded"]), 6)
        self.assertEqual(len([event for event in events if event["event_type"] == "session.started"]), 4)

    def test_resolution_and_correction_append_without_rewriting_initial_problem(self):
        self.event_store.append_event(self.binding, {"event_type": "issue.opened", "issue_id": "issue-one", "summary": "Synthetic environment failure.", "category": "environment", "attribution": "environment"}, "open-one")
        before = self.history_bytes()
        self.event_store.append_event(self.binding, {"event_type": "issue.corrected", "issue_id": "issue-one", "causes": ["open-one"], "data": {"issue": {"category": "tool"}}}, "correct-one")
        self.event_store.append_event(self.binding, {"event_type": "issue.resolved", "issue_id": "issue-one", "causes": ["correct-one"]}, "resolve-one")
        self.assert_history_preserved(before)
        issue = self.projection.read_snapshot(self.binding)["issues"][0]
        self.assertEqual(issue["status"], "resolved")
        self.assertEqual(issue["category"], "tool")
        self.assertEqual(set(issue["causes"]), {"open-one", "correct-one"})

    def test_operational_prompts_raw_output_and_credentials_are_rejected_before_persistence(self):
        before = self.history_bytes()
        for data in ({"stdout": "raw output"}, {"nested": {"prompt": "raw prompt"}}, {"evidence": "ghp_" + "a" * 30}, {"authorization": "Bearer " + "a" * 30}):
            with self.subTest(data=data), self.assertRaises(self.event_store.EventStoreError):
                self.event_store.append_event(self.binding, {"event_type": "issue.opened", "issue_id": "unsafe-issue", "data": data})
        self.assertEqual(self.history_bytes(), before)

    def test_valid_json_tampering_is_detected_before_projection_or_retry(self):
        payload = {"event_type": "issue.opened", "issue_id": "tampered-issue", "summary": "Original synthetic evidence."}
        self.event_store.append_event(self.binding, payload, "tamper-event")
        path = next(Path(self.binding["events_root"]).rglob("tamper-event.json"))
        changed = json.loads(path.read_text())
        changed["summary"] = "Altered synthetic evidence."
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaises(self.event_store.EventStoreError):
            self.projection.read_snapshot(self.binding)
        with self.assertRaises(self.event_store.EventStoreError):
            self.event_store.append_event(self.binding, payload, "tamper-event")

    def test_malformed_history_fails_closed_instead_of_showing_empty_metrics(self):
        self.event_store.append_event(self.binding, {"event_type": "attempt.recorded", "attempt_id": "broken-attempt"}, "broken-event")
        path = next(Path(self.binding["events_root"]).rglob("broken-event.json"))
        path.write_bytes(b"{broken")
        with self.assertRaises(self.event_store.EventStoreError):
            self.projection.read_snapshot(self.binding)

    def test_distinct_attempts_and_model_provenance_do_not_blame_environment_failures(self):
        declared = {"provider": "synthetic", "requested": "model-one", "source": "declared"}
        observed = {"provider": "synthetic", "observed": "model-two", "source": "observed"}
        self.event_store.append_event(self.binding, {"event_type": "issue.opened", "issue_id": "environment-issue", "attribution": "environment"}, "environment-issue-open")
        self.event_store.append_event(self.binding, {"event_type": "issue.opened", "issue_id": "model-issue", "attribution": "confirmed_model"}, "model-issue-open")
        for identifier, attempt, issue, model in (("one", "attempt-one", "environment-issue", declared), ("two", "attempt-one", "environment-issue", declared), ("three", "attempt-two", "model-issue", observed), ("four", "attempt-three", None, {})):
            self.event_store.append_event(self.binding, {"event_type": "attempt.recorded", "attempt_id": attempt, "issue_id": issue, "model": model}, "attempt-event-" + identifier)
        rows = {row["source"]: row for row in self.projection.read_snapshot(self.binding)["models"]}
        self.assertEqual(sum(row["attempt_count"] for row in rows.values()), 3)
        self.assertEqual(rows["declared"]["attempt_count"], 1)
        self.assertEqual(rows["declared"]["issue_count"], 1)
        self.assertEqual(rows["declared"]["confirmed_model_issue_count"], 0)
        self.assertEqual(rows["observed"]["confirmed_model_issue_count"], 1)
        self.assertIsNone(rows["unknown"]["observed"])
        self.assertIsNone(rows["unknown"]["requested"])
        self.assertFalse(any(key in row for row in rows.values() for key in ("error_rate", "tokens", "cost")))

    def test_cursor_reads_immutable_history_without_duplicate_or_lost_events(self):
        for index in range(5):
            self.event_store.append_event(self.binding, {"event_type": "attempt.recorded", "attempt_id": "page-attempt-" + str(index)}, "page-event-" + str(index))
        before = self.history_bytes()
        seen = []
        filters = {"event_type": "attempt.recorded", "limit": 2}
        while True:
            snapshot = self.projection.read_snapshot(self.binding, filters)
            seen.extend(event["event_id"] for event in snapshot["events"])
            if not snapshot["next_cursor"]:
                break
            filters["cursor"] = snapshot["next_cursor"]
        self.assertEqual(seen, ["page-event-" + str(index) for index in range(5)])
        self.assertEqual(self.history_bytes(), before)
