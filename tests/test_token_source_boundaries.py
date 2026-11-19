"""Explicit source boundaries, unsupported data and safe failure visibility."""
import contextlib
import io
import json
import os
from unittest import mock

from token_usage_fixtures import TokenUsageCase, ROOT_THREAD, FRONTEND_THREAD, QA_THREAD, PRIVATE_MARKER, record, response, usage


class TokenSourceBoundaryTests(TokenUsageCase):
    def test_no_registered_source_reports_unknown_usage_not_a_measured_zero(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot["status"], "unavailable")
        self.assertEqual(snapshot["responses"], [])
        counts = snapshot["totals"]["own"]
        if counts is not None:
            self.assertIsNone(counts["total_tokens"])
            self.assertIsNone(counts["input_tokens"])
        self.assertIsNone(snapshot["unassigned"]["response_count"])

    def test_source_root_outside_explicit_codex_home_is_rejected(self):
        outside = self.fake_home / "unrelated-conversations"
        outside.mkdir()
        path = outside / ("rollout-2026-11-19T12-00-00-" + ROOT_THREAD + ".jsonl")
        self.write_records(path, [record("session_meta", {"id": ROOT_THREAD, "source": "cli"}), response()])
        with self.assertRaises(self.tokens.TokenUsageError):
            self.tokens.register_source(self.binding, {"thread_id": ROOT_THREAD, "source_root": str(outside)})
        self.assertEqual(self.snapshot()["responses"], [])

    def test_cumulative_only_source_does_not_invent_measured_response_usage(self):
        path = self.create_source()
        self.start_goal()
        self.append_records(path, record("event_msg", {"type": "token_count", "info": {
            "total_token_usage": usage(10000, 9000, 1000, 500, 11000),
            "last_token_usage": usage(100, 80, 20, 5, 120)}}))
        self.tokens.sync_usage(self.binding, {})
        snapshot = self.snapshot()
        self.assertEqual(snapshot["responses"], [])
        self.assertIsNone(snapshot["totals"]["own"]["input_tokens"])
        self.assertIsNone(snapshot["totals"]["own"]["total_tokens"])

    def test_private_registry_cannot_be_created_in_a_versionable_codex_home(self):
        home = self.project / "native-profile"
        sessions = home / "sessions"
        sessions.mkdir(parents=True)
        source = self.create_source()
        (sessions / source.name).write_bytes(source.read_bytes())
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(home)}):
            with self.assertRaises(self.tokens.TokenUsageError):
                self.tokens.register_source(self.binding, {"thread_id": ROOT_THREAD, "source_root": str(sessions)})
        self.assertFalse((home / "gag-dev-team").exists())

    def test_registered_filename_cannot_read_a_symbolic_link_outside_source_root(self):
        path = self.create_source()
        self.add_context(path)
        self.append_records(path, response())
        target = self.fake_home / "outside-source.jsonl"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        try:
            self.tokens.register_source(self.binding, {"thread_id": ROOT_THREAD, "source_root": str(self.source_root)})
            self.tokens.sync_usage(self.binding, {})
        except self.tokens.TokenUsageError:
            pass
        self.assertEqual(self.snapshot()["responses"], [])
        self.assertEqual(target.read_bytes().count(b"token_usage_record"), 1)

    def test_native_header_must_match_the_registered_thread_identity(self):
        path = self.create_source()
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[0]["payload"]["id"] = QA_THREAD
        self.write_records(path, records + [response()])
        try:
            self.tokens.register_source(self.binding, {"thread_id": ROOT_THREAD, "source_root": str(self.source_root)})
            self.tokens.sync_usage(self.binding, {})
        except self.tokens.TokenUsageError:
            pass
        snapshot = self.snapshot()
        self.assertEqual(snapshot["responses"], [])
        self.assertNotEqual(snapshot["status"], "available")

    def test_malformed_native_lines_preserve_history_and_never_copy_conversation_content(self):
        path = self.create_source()
        self.add_context(path)
        self.start_goal()
        self.append_records(path, response())
        self.tokens.sync_usage(self.binding, {})
        before = self.history_bytes()
        with path.open("a", encoding="utf-8") as stream:
            stream.write('{"type":"token_usage_record","payload":{"message":"' + PRIVATE_MARKER + '\n')
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                self.tokens.sync_usage(self.binding, {})
            except self.tokens.TokenUsageError as error:
                self.assertNotIn(PRIVATE_MARKER, str(error))
        self.assertNotIn(PRIVATE_MARKER, output.getvalue() + errors.getvalue())
        self.assertEqual(self.snapshot()["totals"]["own"]["total_tokens"], 120)
        self.assertIn(self.snapshot()["status"], {"partial", "incompatible", "stale", "unavailable"})
        self.tokens.sync_usage(self.binding, {})
        self.assertIn(self.snapshot()["status"], {"partial", "incompatible", "stale", "unavailable"})
        self.assert_history_preserved(before)
        self.assert_private_content_absent()

    def test_child_parent_claim_must_match_verified_native_ancestry(self):
        self.create_source()
        child = self.create_source(FRONTEND_THREAD, QA_THREAD)
        records = [json.loads(line) for line in child.read_text(encoding="utf-8").splitlines()]
        records[0]["payload"]["session_id"] = QA_THREAD
        self.write_records(child, records)
        self.add_context(child)
        self.start_goal()
        foreign_response = response(FRONTEND_THREAD, "child-response")
        foreign_response["payload"]["session_id"] = QA_THREAD
        self.append_records(child, foreign_response)
        try:
            self.tokens.link_agent(self.binding, {"goal_id": "goal-alpha", "thread_id": FRONTEND_THREAD,
                "parent_thread_id": ROOT_THREAD, "source_root": str(self.source_root), "agent_name": "environment_frontend"})
            self.tokens.sync_usage(self.binding, {})
        except self.tokens.TokenUsageError:
            pass
        self.assertEqual(self.snapshot()["responses"], [])

