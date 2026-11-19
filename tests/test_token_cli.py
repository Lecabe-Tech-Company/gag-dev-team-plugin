"""Real Node-to-Python commands use synthetic credentials and private UTF-8 stdin."""
import json
import os
import subprocess

from test_project_cli import ROOT
from token_usage_fixtures import TokenUsageCase, ROOT_THREAD, PRIVATE_MARKER, response


class TokenCliTests(TokenUsageCase):
    def command(self, action, payload=None, *arguments):
        completed = subprocess.run(["node", str(ROOT / "bin/gag-dev-team.cjs"), "environment",
            action, "--project", str(self.project), *arguments],
            input="" if payload is None else json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, timeout=30, env=dict(os.environ, PYTHONUTF8="0"))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_goal_sync_filters_correction_and_end_work_through_the_real_node_wrapper(self):
        path = self.create_source()
        self.add_context(path)
        title = "Objetivo de consumo — 日本語 🙂"
        started = self.command("goal-start", {"goal_id": "goal-alpha", "name": title,
            "thread_id": ROOT_THREAD, "source_root": str(self.source_root)})
        self.append_records(path, response())
        before = self.history_bytes()
        first_read = self.command("snapshot", None, "--goal-id", "goal-alpha")
        self.assertEqual(first_read["token_usage"]["responses"], [])
        self.assertEqual(self.history_bytes(), before)
        synchronized = self.command("usage-sync")
        self.assertEqual(synchronized["observations_added"], 1)
        selected = self.command("snapshot", None, "--goal-id", "goal-alpha",
            "--agent-id", started["source"]["agent_id"], "--model", "synthetic-model-a")
        self.assertEqual(selected["token_usage"]["goals"][0]["name"], title)
        self.assertEqual(selected["token_usage"]["totals"]["own"]["total_tokens"], 120)
        self.assertEqual(selected["token_usage"]["filters"]["goal_id"], "goal-alpha")
        ended = self.command("goal-end", {"goal_id": "goal-alpha"})
        self.assertEqual(ended["goal_id"], "goal-alpha")
        self.append_records(path, response(response_id="outside-goal"))
        self.command("usage-sync")
        self.assertEqual(self.snapshot()["unassigned"]["response_count"], 1)
        corrected = self.command("usage-correct", {"thread_id": ROOT_THREAD, "response_id": "outside-goal",
            "goal_id": "goal-alpha", "reason": "Explicit synthetic ownership correction."})
        self.assertTrue(corrected["created"])
        self.assertEqual(self.goal("goal-alpha")["inclusive"]["response_count"], 2)

    def test_concurrent_node_processes_do_not_duplicate_a_response(self):
        path = self.create_source()
        self.add_context(path)
        self.start_goal()
        self.append_records(path, response())
        command = ["node", str(ROOT / "bin/gag-dev-team.cjs"), "environment", "usage-sync",
                   "--project", str(self.project)]
        processes = [subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _index in range(4)]
        results = []
        for process in processes:
            output, errors = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, errors)
            results.append(json.loads(output))
        self.assertEqual(sum(item["observations_added"] for item in results), 1)
        self.assertEqual(self.own()["response_count"], 1)
        self.assertEqual(self.own()["total_tokens"], 120)

    def test_malformed_private_input_is_not_echoed_and_never_starts_a_goal(self):
        result = subprocess.run(["node", str(ROOT / "bin/gag-dev-team.cjs"), "environment", "goal-start",
            "--project", str(self.project)], input='{"private":"' + PRIVATE_MARKER,
            capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(PRIVATE_MARKER, result.stdout + result.stderr)
        self.assertEqual(self.snapshot()["goals"], [])

