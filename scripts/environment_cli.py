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
    for name in ("identity", "binding", "snapshot", "record", "claim-legacy", "dashboard"):
        command = commands.add_parser(name)
        command.add_argument("--project", default=".")
        command.add_argument("--host")
        if name == "snapshot":
            command.add_argument("--bound", action="store_true")
            command.add_argument("--period", choices=("all", "24h", "7d", "30d"), default="all")
            for field in ("from", "to", "model", "category", "status", "cursor"):
                command.add_argument("--" + field)
            command.add_argument("--limit", type=int, default=100)
        if name == "record":
            command.add_argument("--event-id")
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
                if args.period != "all" and not filters["from"]:
                    duration = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}[args.period]
                    filters["from"] = (datetime.now(timezone.utc) - duration).isoformat()
                result = read_snapshot(binding, filters)
            elif args.action == "record":
                result = append_event(binding, read_input(), args.event_id)
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
