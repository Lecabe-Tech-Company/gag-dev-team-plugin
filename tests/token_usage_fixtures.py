"""Synthetic Codex metadata fixtures; never read real session directories."""
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
from unittest import mock

from environment_fixtures import EnvironmentCase


ROOT_THREAD = "11111111-1111-4111-8111-111111111111"
FRONTEND_THREAD = "22222222-2222-4222-8222-222222222222"
QA_THREAD = "33333333-3333-4333-8333-333333333333"
NEXT_ROOT_THREAD = "44444444-4444-4444-8444-444444444444"
COUNTERS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
            "output_tokens", "reasoning_output_tokens", "total_tokens")
PRIVATE_MARKER = "SYNTHETIC_CONVERSATION_CREDENTIAL_CANARY_086"


def timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def usage(input_tokens=100, cached_input_tokens=80, output_tokens=20,
          reasoning_output_tokens=5, total_tokens=120, cache_write_input_tokens=None):
    result = {"input_tokens": input_tokens, "cached_input_tokens": cached_input_tokens,
              "output_tokens": output_tokens, "reasoning_output_tokens": reasoning_output_tokens,
              "total_tokens": total_tokens}
    if cache_write_input_tokens is not None:
        result["cache_write_input_tokens"] = cache_write_input_tokens
    return result


def record(kind, payload, recorded_at=None):
    return {"timestamp": recorded_at or timestamp(), "type": kind, "payload": payload}


def response(thread_id=ROOT_THREAD, response_id="response-one", turn_id="turn-one",
             counters=None, recorded_at=None):
    return record("token_usage_record", {
        "thread_id": thread_id, "session_id": ROOT_THREAD,
        "root_turn_id": turn_id if thread_id == ROOT_THREAD else "turn-one",
        "turn_id": turn_id, "response_id": response_id,
        "usage": usage() if counters is None else counters,
        "turn_token_usage": usage(900000, 800000, 200000, 50000, 1100000),
        "thread_token_usage": usage(9000000, 8000000, 2000000, 500000, 11000000),
    }, recorded_at)


class TokenUsageCase(EnvironmentCase):
    def setUp(self):
        super().setUp()
        self.codex_home = self.fake_home / ".codex"
        self.source_root = self.codex_home / "sessions"
        self.source_root.mkdir(parents=True)
        environment = mock.patch.dict(os.environ, {
            "CODEX_HOME": str(self.codex_home), "HOME": str(self.fake_home),
            "USERPROFILE": str(self.fake_home), "XDG_DATA_HOME": str(self.fake_home / ".local/share"),
            "LOCALAPPDATA": str(self.fake_home / "AppData/Local"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.tokens = importlib.import_module("token_usage")

    def create_source(self, thread_id=ROOT_THREAD, parent_thread_id=None):
        source = "cli" if parent_thread_id is None else {"subagent": {"thread_spawn": {
            "parent_thread_id": parent_thread_id, "depth": 1 if parent_thread_id == ROOT_THREAD else 2}}}
        header = record("session_meta", {
            "id": thread_id, "session_id": thread_id if parent_thread_id is None else ROOT_THREAD,
            "timestamp": timestamp(),
            "cwd": str(self.project), "originator": "codex_cli_rs",
            "cli_version": "0.167.2", "source": source, "model_provider": "openai",
        })
        path = self.source_root / ("rollout-2026-11-19T12-00-00-" + thread_id + ".jsonl")
        self.write_records(path, [header])
        return path

    def write_records(self, path, records):
        path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")

    def append_records(self, path, *records):
        with path.open("a", encoding="utf-8") as stream:
            for item in records:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")

    def add_context(self, path, turn_id="turn-one", model="synthetic-model-a"):
        self.append_records(path, record("turn_context", {"turn_id": turn_id, "model": model}))

    def start_goal(self, goal_id="goal-alpha", name="Synthetic alpha goal", thread_id=ROOT_THREAD):
        return self.tokens.start_goal(self.binding, {"goal_id": goal_id, "name": name,
            "thread_id": thread_id, "source_root": str(self.source_root)})

    def snapshot(self, **filters):
        return self.tokens.usage_snapshot(self.binding, filters or None)

    def own(self, snapshot=None):
        return (snapshot or self.snapshot())["totals"]["own"]

    def goal(self, goal_id, snapshot=None):
        return next(item for item in (snapshot or self.snapshot())["goals"] if item["id"] == goal_id)

    def assert_private_content_absent(self):
        for root in (Path(self.binding["account_root"]), self.codex_home / "gag-dev-team"):
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    self.assertNotIn(PRIVATE_MARKER.encode(), path.read_bytes(), str(path.relative_to(root)))
        self.assertNotIn(PRIVATE_MARKER, json.dumps(self.snapshot(), ensure_ascii=False))

