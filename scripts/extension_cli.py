"""Explicit user-local extension actions without prompt classification."""
import argparse
import json

from environment_cli import read_input


def run_extension_cli(arguments):
    from environment_identity import project_binding, resolve_identity
    from personal_extensions import activate_skill, download_skill, install_native_plugin, load_personal_skill, review_extension
    from environment_projection import read_snapshot
    from event_store import append_event
    parser = argparse.ArgumentParser(prog="gag-dev-team extensions")
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("list", "download-skill", "review", "activate", "load", "deactivate", "install-plugin"):
        command = commands.add_parser(name)
        command.add_argument("--project", default=".")
        command.add_argument("--host")
        if name in {"review", "activate", "load", "deactivate"}:
            command.add_argument("extension_id")
            command.add_argument("--digest", required=True)
        if name == "download-skill":
            command.add_argument("--repository", required=True)
            command.add_argument("--path", required=True)
            command.add_argument("--ref", default="HEAD")
        if name == "install-plugin":
            command.add_argument("target")
            command.add_argument("--harness", choices=("codex", "claude"), required=True)
    args = parser.parse_args(arguments)
    try:
        binding = project_binding(args.project, resolve_identity(args.host))
        if args.action == "list":
            result = {"extensions": read_snapshot(binding)["extensions"]}
        elif args.action == "download-skill":
            result = download_skill(binding, args.repository, args.path, args.ref)
        elif args.action == "review":
            result = review_extension(binding, args.extension_id, args.digest, read_input())
        elif args.action == "activate":
            result = activate_skill(binding, args.extension_id, args.digest)
        elif args.action == "load":
            result = load_personal_skill(binding, args.extension_id, args.digest)
        elif args.action == "deactivate":
            result = append_event(binding, {"event_type": "extension.deactivated", "data": {"extension_id": args.extension_id, "digest": args.digest, "state": "deactivated"}})
        else:
            result = install_native_plugin(binding, args.target, args.harness, read_input())
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return result
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        parser.exit(1, f"Personal extension operation failed: {error}\n")
