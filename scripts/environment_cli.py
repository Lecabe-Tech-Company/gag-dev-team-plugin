"""Account-scoped environment commands; private payloads travel through stdin."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone


def read_input() -> dict:
    raw = sys.stdin.buffer.read(262145)
    if len(raw) > 262144:
        raise ValueError("Input exceeds the private payload limit.")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("A JSON object is required.")
    return payload


def run_environment_cli(arguments):
    from environment_identity import project_binding, resolve_identity
    from event_store import append_event

    parser = argparse.ArgumentParser(prog="gag-dev-team environment")
    commands = parser.add_subparsers(dest="action", required=True)
    actions = ("identity", "binding", "snapshot", "record", "claim-legacy", "dashboard",
               "goal-start", "goal-end", "source-register", "agent-link", "usage-sync", "usage-correct")
    for name in actions:
        command = commands.add_parser(name)
        command.add_argument("--project", default=".")
        command.add_argument("--host")
        if name == "snapshot":
            command.add_argument("--bound", action="store_true")
            command.add_argument("--period", choices=("all", "24h", "1d", "7d", "30d", "90d"), default="all")
            for field in ("from", "to", "model", "category", "status", "cursor", "goal-id", "agent-id"):
                command.add_argument("--" + field)
            command.add_argument("--limit", type=int, default=100)
        if name == "record":
            command.add_argument("--event-id")
        if name == "usage-sync":
            command.add_argument("--source-id")
    args = parser.parse_args(arguments)
    try:
        if args.action == "identity":
            result = resolve_identity(args.host)
        else:
            if args.action == "snapshot" and args.bound:
                supplied = read_input()
                binding = project_binding(supplied["project_root"], supplied["user"])
                if any(binding.get(key) != supplied.get(key) for key in binding):
                    raise ValueError("The dashboard binding no longer matches this project.")
            else:
                binding = project_binding(args.project, resolve_identity(args.host))
            if args.action == "binding":
                result = binding
            elif args.action == "snapshot":
                from environment_projection import read_snapshot
                if not 1 <= args.limit <= 200:
                    raise ValueError("Snapshot limit must be between 1 and 200.")
                filters = {key: getattr(args, key) for key in ("from", "to", "model", "category", "status", "cursor", "limit")}
                filters["goal_id"] = getattr(args, "goal_id")
                filters["agent_id"] = getattr(args, "agent_id")
                if args.period != "all" and not filters["from"]:
                    duration = {"24h": timedelta(hours=24), "1d": timedelta(days=1), "7d": timedelta(days=7),
                                "30d": timedelta(days=30), "90d": timedelta(days=90)}[args.period]
                    filters["from"] = (datetime.now(timezone.utc) - duration).isoformat()
                result = read_snapshot(binding, filters)
            elif args.action == "record":
                result = append_event(binding, read_input(), args.event_id)
            elif args.action in {"goal-start", "goal-end", "source-register", "agent-link", "usage-sync", "usage-correct"}:
                from token_usage import (TokenUsageError, correct_attribution, end_goal, link_agent,
                                         register_source, start_goal, sync_usage)
                payload = read_input() if args.action != "usage-sync" else {"source_id": args.source_id}
                operations = {"goal-start": start_goal, "goal-end": end_goal,
                              "source-register": register_source, "agent-link": link_agent,
                              "usage-sync": sync_usage, "usage-correct": correct_attribution}
                result = operations[args.action](binding, payload)
            elif args.action == "claim-legacy":
                from legacy_import import claim_legacy
                result = claim_legacy(binding, read_input())
            else:
                from dashboard_service import ensure_dashboard
                result = ensure_dashboard(binding)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return result
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        parser.exit(1, f"Environment operation failed: {error}\n")
