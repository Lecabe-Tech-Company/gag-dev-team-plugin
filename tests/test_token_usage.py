"""ESP-086 response accounting, explicit attribution and private source boundaries."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import subprocess

from token_usage_fixtures import (TokenUsageCase, ROOT_THREAD, FRONTEND_THREAD, QA_THREAD, NEXT_ROOT_THREAD,
                                  PRIVATE_MARKER, COUNTERS, record, response, usage)


class TokenImportTests(TokenUsageCase):
    def ready_source(self):
        path = self.create_source()
        self.add_context(path)
        self.start_goal()
        return path

    def test_response_counters_ignore_accumulated_snapshots_and_preserve_missing_values(self):
        path = self.ready_source()
        self.append_records(path, response())
        result = self.tokens.sync_usage(self.binding, {})
        self.assertEqual(result["observations_added"], 1)
        counts = self.own()
        self.assertEqual(counts["response_count"], 1)
        self.assertEqual({field: counts[field] for field in COUNTERS}, {
            "input_tokens": 100, "cached_input_tokens": 80, "cache_write_input_tokens": None,
            "output_tokens": 20, "reasoning_output_tokens": 5, "total_tokens": 120})
        self.assertEqual(self.snapshot()["responses"][0]["usage"]["total_tokens"], 120)
        with self.subTest(scope="root-history-before-goal"):
            header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            created_at = datetime.fromisoformat(header["timestamp"].replace("Z", "+00:00"))
            goal_at = datetime.fromisoformat(self.goal("goal-alpha")["started_at"].replace("Z", "+00:00"))
            earlier = (created_at + (goal_at - created_at) / 2).isoformat()
            self.append_records(path, response(response_id="historical-root-response", recorded_at=earlier,
                counters=usage(1000, 800, 200, 50, 1200)))
            self.tokens.sync_usage(self.binding, {})
            snapshot = self.snapshot()
            self.assertEqual(snapshot["unassigned"]["response_count"], 1)
            own_total = snapshot["totals"]["own"]["total_tokens"]
            inclusive_total = snapshot["totals"]["inclusive"]["total_tokens"]
            self.assertIsNotNone(own_total)
            self.assertIsNotNone(inclusive_total)
            self.assertGreaterEqual(inclusive_total, own_total)
            root_agent = next(item for item in snapshot["agents"] if item["parent_agent_id"] is None)
            selected = self.snapshot(agent_id=root_agent["id"])
            self.assertEqual(selected["unassigned"]["response_count"], 1)
            self.assertEqual(selected["totals"]["inclusive"]["total_tokens"], inclusive_total)
            self.assertEqual(self.snapshot(model="synthetic-model-a")["unassigned"]["response_count"], 1)
            self.assertEqual(self.snapshot(goal_id="goal-alpha")["totals"]["inclusive"]["total_tokens"], 120)

    def test_repeated_response_and_updated_accumulated_counts_never_add_usage(self):
        path = self.ready_source()
        first = response()
        self.append_records(path, first)
        self.tokens.sync_usage(self.binding, {})
        before = self.history_bytes()
        repeated = json.loads(json.dumps(first))
        repeated["payload"]["turn_token_usage"]["total_tokens"] = 999999999
        self.append_records(path, repeated, record("event_msg", {"type": "token_count",
            "info": {"total_token_usage": usage(999999, 900000, 100000, 10000, 1099999)}}))
        self.tokens.sync_usage(self.binding, {})
        self.tokens.sync_usage(self.binding, {})
        self.assertEqual(self.own()["response_count"], 1)
        self.assertEqual(self.own()["total_tokens"], 120)
        self.assert_history_preserved(before)

    def test_explicit_zero_remains_zero_and_missing_counters_do_not_become_zero(self):
        path = self.ready_source()
        self.append_records(path, response(response_id="zero-response", counters=usage(0, 0, 0, 0, 0, 0)),
                            response(response_id="partial-response", counters={"total_tokens": 5}))
        self.tokens.sync_usage(self.binding, {})
        snapshot = self.snapshot()
        counts = snapshot["totals"]["own"]
        self.assertEqual(counts["response_count"], 2)
        self.assertEqual(counts["total_tokens"], 5)
        self.assertIsNone(counts["input_tokens"])
        self.assertIsNone(counts["cache_write_input_tokens"])
        zero = next(item for item in snapshot["responses"] if item["usage"]["total_tokens"] == 0)
        self.assertEqual(zero["usage"]["input_tokens"], 0)
        self.assertEqual(zero["usage"]["cache_write_input_tokens"], 0)

    def test_invalid_native_counters_preserve_previously_recorded_usage(self):
        path = self.ready_source()
        self.append_records(path, response())
        self.tokens.sync_usage(self.binding, {})
        before = self.history_bytes()
        valid_source = path.read_text(encoding="utf-8")
        for index, invalid in enumerate((-1, True, 1.5, "100", PRIVATE_MARKER, 2 ** 64)):
            with self.subTest(value=invalid):
                path.rename(path.with_suffix(".invalid-" + str(index) + ".old"))
                path.write_text(valid_source, encoding="utf-8")
                counters = usage()
                counters["input_tokens"] = invalid
                self.append_records(path, response(response_id="invalid-" + str(index), counters=counters))
                self.tokens.sync_usage(self.binding, {})
                self.assertEqual(self.own()["response_count"], 1)
                self.assertEqual(self.own()["total_tokens"], 120)
                self.assert_history_preserved(before)
        self.assert_private_content_absent()

    def test_conversation_and_credentials_never_enter_events_projection_or_parser_output(self):
        path = self.create_source()
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        records[0]["payload"].update({"base_instructions": {"text": PRIVATE_MARKER},
                                     "creator_user_id": PRIVATE_MARKER, "creator_account_id": PRIVATE_MARKER})
        self.write_records(path, records)
        self.add_context(path)
        self.start_goal()
        self.append_records(path,
            record("response_item", {"role": "user", "content": [{"text": PRIVATE_MARKER}]}),
            record("response_item", {"role": "assistant", "content": [{"text": PRIVATE_MARKER}]}),
            record("response_item", {"type": "function_call_output", "output": PRIVATE_MARKER}),
            record("event_msg", {"type": "agent_message", "message": PRIVATE_MARKER}),
            response())
        parsed = self.tokens.read_rollout(path, ROOT_THREAD)
        self.assertNotIn(PRIVATE_MARKER, json.dumps(parsed, ensure_ascii=False))
        self.tokens.sync_usage(self.binding, {})
        self.assertEqual(self.own()["total_tokens"], 120)
        self.assert_private_content_absent()
        rendered = json.dumps(self.snapshot(), ensure_ascii=False)
        self.assertNotIn(str(self.source_root), rendered)
        self.assertNotIn("source_root", rendered)

    def test_only_registered_thread_files_are_read(self):
        path = self.ready_source()
        foreign = self.create_source(QA_THREAD)
        self.add_context(foreign)
        self.append_records(foreign, response(QA_THREAD, "foreign-response", counters=usage(5000, 0, 500, 0, 5500)))
        self.append_records(path, response())
        result = self.tokens.sync_usage(self.binding, {})
        self.assertEqual(result["files_read"], 1)
        self.assertEqual(self.own()["response_count"], 1)
        self.assertEqual(self.own()["total_tokens"], 120)

    def test_concurrent_sync_imports_each_response_once(self):
        path = self.ready_source()
        self.append_records(path, response())
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.tokens.sync_usage(self.binding, {}), range(4)))
        self.assertEqual(sum(item["observations_added"] for item in results), 1)
        self.assertEqual(self.own()["response_count"], 1)
        self.assertEqual(self.own()["total_tokens"], 120)

    def test_rotation_truncation_and_replay_keep_history_without_double_counting(self):
        path = self.ready_source()
        first = response()
        self.append_records(path, first)
        self.tokens.sync_usage(self.binding, {})
        before = self.history_bytes()
        header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        path.rename(path.with_suffix(".old"))
        self.write_records(path, [header, record("turn_context", {"turn_id": "turn-one", "model": "synthetic-model-a"}),
                                  first, response(response_id="response-two")])
        self.tokens.sync_usage(self.binding, {})
        self.assertEqual(self.own()["response_count"], 2)
        self.assertEqual(self.own()["total_tokens"], 240)
        self.write_records(path, [header])
        self.tokens.sync_usage(self.binding, {})
        self.append_records(path, first)
        self.tokens.sync_usage(self.binding, {})
        self.assertEqual(self.own()["response_count"], 2)
        self.assertEqual(self.own()["total_tokens"], 240)
        state_path = Path(self.binding["account_root"]) / "runtime/token-usage/state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["checkpoints"] = {}
        state_path.write_text(json.dumps(state), encoding="utf-8")
        self.tokens.sync_usage(self.binding, {})
        self.assertEqual(self.own()["response_count"], 2)
        self.assertEqual(self.own()["total_tokens"], 240)
        self.assert_history_preserved(before)

    def test_snapshot_reads_never_sync_or_mutate_private_history(self):
        path = self.ready_source()
        self.append_records(path, response())
        self.tokens.sync_usage(self.binding, {})
        before = self.history_bytes()
        synced_at = self.snapshot()["last_synced_at"]
        self.append_records(path, response(response_id="not-yet-synced"))
        self.assertEqual(self.snapshot()["totals"]["own"]["response_count"], 1)
        self.assertEqual(self.projection.read_snapshot(self.binding)["token_usage"]["totals"]["own"]["response_count"], 1)
        self.assertEqual(self.snapshot()["last_synced_at"], synced_at)
        self.assertEqual(self.history_bytes(), before)


class TokenAttributionTests(TokenUsageCase):
    def test_agent_tree_reports_own_and_inclusive_usage_without_double_counting(self):
        root = self.create_source()
        frontend = self.create_source(FRONTEND_THREAD, ROOT_THREAD)
        qa = self.create_source(QA_THREAD, FRONTEND_THREAD)
        for path in (root, frontend, qa):
            self.add_context(path)
        self.start_goal()
        frontend_link = self.tokens.link_agent(self.binding, {"goal_id": "goal-alpha", "thread_id": FRONTEND_THREAD,
            "parent_thread_id": ROOT_THREAD, "source_root": str(self.source_root), "agent_name": "environment_frontend"})
        qa_link = self.tokens.link_agent(self.binding, {"goal_id": "goal-alpha", "thread_id": QA_THREAD,
            "parent_thread_id": FRONTEND_THREAD, "source_root": str(self.source_root), "agent_name": "language_qa"})
        self.append_records(root, response())
        self.append_records(frontend, response(FRONTEND_THREAD, "frontend-response", counters=usage(50, 40, 10, 2, 60)))
        self.append_records(qa, response(QA_THREAD, "qa-response", counters=usage(25, 20, 5, 1, 30)))
        self.tokens.sync_usage(self.binding, {})
        snapshot = self.snapshot()
        goal = self.goal("goal-alpha", snapshot)
        self.assertEqual(goal["own"]["total_tokens"], 120)
        self.assertEqual(goal["inclusive"]["total_tokens"], 210)
        self.assertEqual(snapshot["totals"]["inclusive"]["total_tokens"], 210)
        agents = {item["id"]: item for item in snapshot["agents"]}
        self.assertEqual(agents[frontend_link["agent_id"]]["own"]["total_tokens"], 60)
        self.assertEqual(agents[frontend_link["agent_id"]]["inclusive"]["total_tokens"], 90)
        self.assertEqual(agents[qa_link["agent_id"]]["own"]["total_tokens"], 30)
        self.assertEqual(len(snapshot["responses"]), 3)
        with self.subTest(filter="selected-parent-agent"):
            selected = self.snapshot(agent_id=frontend_link["agent_id"])
            selected_agent = next(item for item in selected["agents"] if item["id"] == frontend_link["agent_id"])
            self.assertEqual(selected_agent["own"]["total_tokens"], 60)
            self.assertEqual(selected_agent["inclusive"]["total_tokens"], 90)
        with self.subTest(scope="same-goal-next-root-session"):
            before = self.history_bytes()
            next_root = self.create_source(NEXT_ROOT_THREAD)
            self.add_context(next_root, model="synthetic-model-b")
            self.tokens.link_agent(self.binding, {"goal_id": "goal-alpha", "thread_id": NEXT_ROOT_THREAD,
                "parent_thread_id": None, "source_root": str(self.source_root), "agent_name": "orchestrator"})
            observation = response(NEXT_ROOT_THREAD, "next-session-response", counters=usage(35, 20, 7, 2, 42))
            observation["payload"]["session_id"] = NEXT_ROOT_THREAD
            self.append_records(next_root, observation)
            self.tokens.sync_usage(self.binding, {})
            continued = self.snapshot()
            self.assertEqual(self.goal("goal-alpha", continued)["own"]["total_tokens"], 162)
            self.assertEqual(self.goal("goal-alpha", continued)["inclusive"]["total_tokens"], 252)
            self.assertEqual(continued["totals"]["own"]["total_tokens"], 162)
            model = next(item for item in continued["models"] if item["name"] == "synthetic-model-b")
            self.assertEqual(model["own"]["total_tokens"], 42)
            self.assert_history_preserved(before)

    def test_agent_reuse_respects_link_intervals_and_keeps_old_responses_unassigned(self):
        root = self.create_source()
        child = self.create_source(QA_THREAD, ROOT_THREAD)
        self.add_context(root)
        self.add_context(child)
        self.append_records(child, response(QA_THREAD, "historic-response", recorded_at="2001-01-01T00:00:00Z"))
        self.start_goal()
        link = {"goal_id": "goal-alpha", "thread_id": QA_THREAD, "parent_thread_id": ROOT_THREAD,
                "source_root": str(self.source_root), "agent_name": "language_qa"}
        alpha_link = self.tokens.link_agent(self.binding, link)
        self.append_records(child, response(QA_THREAD, "alpha-response"))
        self.tokens.sync_usage(self.binding, {})
        self.tokens.end_goal(self.binding, {"goal_id": "goal-alpha"})
        self.start_goal("goal-beta", "Synthetic beta goal")
        self.tokens.link_agent(self.binding, {**link, "goal_id": "goal-beta"})
        self.append_records(child, response(QA_THREAD, "beta-response"))
        self.tokens.sync_usage(self.binding, {})
        snapshot = self.snapshot()
        self.assertEqual(self.goal("goal-alpha", snapshot)["inclusive"]["response_count"], 1)
        self.assertEqual(self.goal("goal-beta", snapshot)["inclusive"]["response_count"], 1)
        self.assertEqual(snapshot["unassigned"]["response_count"], 1)
        with self.subTest(filter="historical-goal-agent-attribution"):
            selected = self.snapshot(goal_id="goal-alpha")
            agent = next(item for item in selected["agents"] if item["id"] == alpha_link["agent_id"])
            self.assertEqual(agent["goal_id"], "goal-alpha")
            self.assertEqual(agent["own"]["response_count"], 1)

    def test_model_is_bound_to_each_turn_and_never_claimed_as_provider_served(self):
        path = self.create_source()
        self.start_goal()
        self.add_context(path, "turn-one", "synthetic-model-a")
        self.append_records(path, response())
        self.add_context(path, "turn-two", "synthetic-model-b")
        self.append_records(path, response(response_id="response-two", turn_id="turn-two"))
        self.append_records(path, response(response_id="unknown-model-response", turn_id="missing-context"))
        self.tokens.sync_usage(self.binding, {})
        snapshot = self.snapshot()
        models = {item["model"]["name"]: item["model"] for item in snapshot["responses"]}
        self.assertIn(None, models)
        for name in ("synthetic-model-a", "synthetic-model-b"):
            self.assertEqual(models[name]["source"], "turn_context")
            self.assertEqual(models[name]["verification"], "requested")
        self.assertIsNone(models[None]["name"])
        self.assertEqual(snapshot["coverage"]["models_known"], 2)

    def test_attribution_correction_is_additive_and_survives_response_replay(self):
        path = self.create_source()
        self.add_context(path)
        self.start_goal()
        first = response()
        self.append_records(path, first)
        self.tokens.sync_usage(self.binding, {})
        self.tokens.end_goal(self.binding, {"goal_id": "goal-alpha"})
        self.start_goal("goal-beta", "Synthetic beta goal")
        self.append_records(path, response(response_id="response-two"))
        self.tokens.sync_usage(self.binding, {})
        before = self.history_bytes()
        correction = self.tokens.correct_attribution(self.binding, {"thread_id": ROOT_THREAD,
            "response_id": "response-one", "goal_id": "goal-beta", "reason": "Explicit synthetic ownership correction."})
        self.assertTrue(correction["created"])
        self.assert_history_preserved(before)
        self.append_records(path, first)
        self.tokens.sync_usage(self.binding, {})
        snapshot = self.snapshot()
        self.assertEqual(self.goal("goal-alpha", snapshot)["inclusive"]["response_count"], 0)
        self.assertEqual(self.goal("goal-beta", snapshot)["inclusive"]["response_count"], 2)
        self.assertEqual(snapshot["totals"]["inclusive"]["total_tokens"], 240)
        self.assertEqual(len(snapshot["responses"]), 2)

    def test_other_accounts_and_projects_do_not_receive_existing_usage(self):
        path = self.create_source()
        self.add_context(path)
        self.start_goal()
        self.append_records(path, response())
        self.tokens.sync_usage(self.binding, {})
        other_account = self.binding_for(202, "second-user")
        self.assertEqual(self.tokens.usage_snapshot(other_account)["responses"], [])
        self.tokens.sync_usage(other_account, {})
        self.assertEqual(self.tokens.usage_snapshot(other_account)["responses"], [])
        other_project = self.fake_home / "other-project"
        other_project.mkdir()
        subprocess.run(["git", "init", "-q", str(other_project)], check=True)
        binding = self.identity_module.project_binding(other_project, self.identity)
        try:
            self.tokens.register_source(binding, {"thread_id": ROOT_THREAD, "source_root": str(self.source_root)})
            self.tokens.sync_usage(binding, {})
        except self.tokens.TokenUsageError:
            pass
        self.assertEqual(self.tokens.usage_snapshot(binding)["responses"], [])
        self.assertEqual(self.snapshot()["totals"]["own"]["response_count"], 1)

    def test_other_project_sync_cannot_take_a_response_from_an_existing_goal(self):
        path = self.create_source()
        self.add_context(path)
        self.start_goal()
        self.append_records(path, response())
        other_project = self.fake_home / "other-project"
        other_project.mkdir()
        subprocess.run(["git", "init", "-q", str(other_project)], check=True)
        binding = self.identity_module.project_binding(other_project, self.identity)
        try:
            self.tokens.register_source(binding, {"thread_id": ROOT_THREAD, "source_root": str(self.source_root)})
            self.tokens.sync_usage(binding, {})
        except self.tokens.TokenUsageError:
            pass
        self.tokens.sync_usage(self.binding, {})
        self.assertEqual(self.tokens.usage_snapshot(binding)["responses"], [])
        self.assertEqual(self.goal("goal-alpha")["inclusive"]["response_count"], 1)
        self.assertEqual(self.goal("goal-alpha")["inclusive"]["total_tokens"], 120)

