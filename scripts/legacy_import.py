"""Import legacy v0.4 user data only after an explicit account-ownership claim."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path, PurePosixPath

try:
    from event_store import EventStoreError, append_event
    from user_rules import _digest, _existing_symlink, private_directory, private_storage_root
except ModuleNotFoundError:
    from scripts.event_store import EventStoreError, append_event
    from scripts.user_rules import _digest, _existing_symlink, private_directory, private_storage_root


class LegacyImportError(RuntimeError):
    """Raised when legacy private data cannot be copied without changing its source."""


def _write_once(path: Path, raw: bytes, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise LegacyImportError("The legacy copy path escapes the account project root.") from error
    current = root
    for part in path.parent.relative_to(root).parts:
        current = current / part
        if _existing_symlink(current):
            raise LegacyImportError("The legacy copy path contains a symbolic link.")
        try:
            current.mkdir(mode=0o700, exist_ok=True)
        except OSError as error:
            raise LegacyImportError("The legacy copy directory cannot be created safely.") from error
        if _existing_symlink(current) or not current.is_dir():
            raise LegacyImportError("The legacy copy directory is unsafe.")
        if os.name != "nt":
            os.chmod(current, 0o700)
    if _existing_symlink(path):
        raise LegacyImportError("The legacy copy target is a symbolic link.")
    if path.exists():
        if path.read_bytes() != raw:
            raise LegacyImportError("An existing immutable legacy copy has different bytes.")
        return False
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".pending")
    if _existing_symlink(temporary):
        raise LegacyImportError("A temporary legacy copy path is unsafe.")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        descriptor = None
    except OSError as error:
        raise LegacyImportError("The exact legacy bytes could not be staged privately.") from error
    if descriptor is not None:
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
                return True
            except FileExistsError:
                if path.read_bytes() != raw:
                    raise LegacyImportError("A competing legacy import wrote different bytes.")
                return False
            except OSError as error:
                raise LegacyImportError("The legacy copy could not be published without overwrite.") from error
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass
    raise LegacyImportError("A concurrent legacy copy is incomplete; retry the import.")


def _read_json(path: Path, limit: int) -> tuple[dict, bytes]:
    if _existing_symlink(path) or not path.is_file() or path.stat().st_size > limit:
        raise LegacyImportError("A legacy source file is unsafe or exceeds the supported size.")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LegacyImportError("A legacy source file is unreadable or corrupt.") from error
    if not isinstance(value, dict):
        raise LegacyImportError("A legacy source file has an unsupported shape.")
    return value, raw


def _copy_legacy_rule_store(project: str, binding: dict) -> list[dict]:
    source_root = private_storage_root(project, "user-rules")
    source_path = source_root / "state.json"
    if not source_path.exists():
        return []
    state, raw = _read_json(source_path, 524288)
    records = state.get("rules")
    if state.get("schema_version") != 1 or not isinstance(records, list):
        raise LegacyImportError("The legacy rules store is not a supported v0.4 store.")
    digest = _digest(raw)
    target = Path(binding["versions_root"]) / "legacy" / f"rules-state-{digest}.json"
    _write_once(target, raw, Path(binding["private_root"]))
    relative_target = target.relative_to(Path(binding["private_root"])).as_posix()
    return [{"record": record, "source_digest": digest, "source_path": relative_target} for record in records]


def _copy_legacy_skill_store(project: str, binding: dict) -> list[dict]:
    source_root = private_storage_root(project, "user-skills")
    source_path = source_root / "catalog.json"
    if not source_path.exists():
        return []
    state, raw = _read_json(source_path, 4 * 1024 * 1024)
    records = state.get("skills")
    if state.get("schema_version") != 1 or not isinstance(records, list):
        raise LegacyImportError("The legacy skills catalog is not a supported v0.4 catalog.")
    catalog_digest = _digest(raw)
    catalog_target = Path(binding["versions_root"]) / "legacy" / f"skills-catalog-{catalog_digest}.json"
    _write_once(catalog_target, raw, Path(binding["private_root"]))
    relative_catalog_target = catalog_target.relative_to(Path(binding["private_root"])).as_posix()
    imported = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("slug"), str):
            raise LegacyImportError("A legacy skill record is malformed.")
        slug = record["slug"]
        if not slug.isascii() or not slug.replace("-", "").isalnum() or slug.startswith("-") or slug.endswith("-"):
            raise LegacyImportError("A legacy skill slug is unsafe.")
        source_directory = source_root / slug
        if _existing_symlink(source_directory) or not source_directory.is_dir():
            raise LegacyImportError("A legacy skill bundle is missing or unsafe.")
        copied_files = []
        for source_file in sorted(source_directory.rglob("*")):
            if _existing_symlink(source_file):
                raise LegacyImportError("A legacy skill bundle contains a symbolic link.")
            if source_file.is_dir():
                continue
            relative = source_file.relative_to(source_directory).as_posix()
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts:
                raise LegacyImportError("A legacy skill file path is unsafe.")
            file_bytes = source_file.read_bytes()
            file_digest = _digest(file_bytes)
            destination = Path(binding["versions_root"]) / "legacy" / "skills" / slug / pure
            _write_once(destination, file_bytes, Path(binding["private_root"]))
            copied_files.append({"path": relative, "sha256": file_digest, "size": len(file_bytes)})
        imported.append({"record": record, "source_digest": catalog_digest,
                         "source_path": relative_catalog_target, "files": copied_files})
    return imported


def claim_legacy(binding: dict, confirmation: dict) -> dict:
    """Copy legacy data only when the agent supplies verified literal ownership evidence."""
    if not isinstance(confirmation, dict) or confirmation.get("ownership_confirmed") is not True:
        raise LegacyImportError("Explicit legacy ownership confirmation is required.")
    evidence = confirmation.get("evidence")
    recorded_by = confirmation.get("recorded_by")
    if (not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 2000
            or not isinstance(recorded_by, str) or not recorded_by.strip() or len(recorded_by) > 120):
        raise LegacyImportError("Legacy ownership confirmation must include concise literal evidence and the recorder.")
    project = binding.get("project_root")
    if not isinstance(project, str) or not project:
        raise LegacyImportError("The verified project root is missing from the account binding.")

    try:
        from user_rules import _account_binding
    except ModuleNotFoundError:
        from scripts.user_rules import _account_binding
    active_binding = _account_binding(project)
    supplied_user, active_user = binding.get("user", {}), active_binding.get("user", {})
    if (supplied_user.get("provider") != active_user.get("provider")
            or supplied_user.get("host") != active_user.get("host")
            or supplied_user.get("id") != active_user.get("id")
            or binding.get("project_id") != active_binding.get("project_id")
            or binding.get("private_root") != active_binding.get("private_root")):
        raise LegacyImportError("The active authenticated account changed; legacy import was not written.")
    # Use the freshly verified login observation while preserving the stable account root.
    binding = active_binding

    try:
        legacy_rules = _copy_legacy_rule_store(project, binding)
        legacy_skills = _copy_legacy_skill_store(project, binding)
        from user_rules import policy_snapshot
    except ModuleNotFoundError:
        from scripts.user_rules import policy_snapshot
    try:
        current_policy = policy_snapshot()["policy_digest"]
    except Exception:
        current_policy = None

    for item in legacy_rules:
        record = item["record"]
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise LegacyImportError("A legacy rule record is malformed.")
        old_status = record.get("status")
        review = record.get("review")
        still_reviewed = (old_status == "active" and isinstance(review, dict)
                          and review.get("decision") == "accept" and current_policy
                          and review.get("policy_digest") == current_policy)
        copied_record = {**record, "status": "active" if still_reviewed else "inactive",
                         "legacy_source_digest": item["source_digest"]}
        append_event(binding, {
            "event_type": "rule.versioned", "category": "rule", "summary": "Imported a legacy private rule after account ownership confirmation.",
            "data": {"record": copied_record, "legacy_source": item["source_path"], "legacy_source_digest": item["source_digest"]},
        }, event_id=f"legacy-rule-{record['id']}-{item['source_digest'][:12]}")

    for item in legacy_skills:
        record = item["record"]
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise LegacyImportError("A legacy skill record is malformed.")
        review = record.get("review")
        still_reviewed = (record.get("status") == "active" and isinstance(review, dict)
                          and review.get("decision") == "accept" and current_policy
                          and review.get("policy_digest") == current_policy)
        copied_record = {**record, "status": "active" if still_reviewed else "inactive",
                         "legacy_source_digest": item["source_digest"], "files": item["files"]}
        append_event(binding, {
            "event_type": "skill.versioned", "category": "skill", "summary": "Imported a legacy private skill after account ownership confirmation.",
            "data": {"record": copied_record, "legacy_source": item["source_path"], "legacy_source_digest": item["source_digest"]},
        }, event_id=f"legacy-skill-{record['id']}-{item['source_digest'][:12]}")

    # Merge imported records into account-local runtime caches only after the immutable copies/events exist.
    # The v0.4 source namespaces remain read-only and untouched.
    try:
        from user_rules import _account_binding, _empty_state as empty_rule_state, _paths as rule_paths, _read_state as read_rule_state, _state_lock as rule_lock, _write_state as write_rule_state
        from user_skills import _empty_state as empty_skill_state, _read_state as read_skill_state, _skill_lock, _state_paths as skill_paths, _write_state as write_skill_state
    except ModuleNotFoundError:
        from scripts.user_rules import _account_binding, _empty_state as empty_rule_state, _paths as rule_paths, _read_state as read_rule_state, _state_lock as rule_lock, _write_state as write_rule_state
        from scripts.user_skills import _empty_state as empty_skill_state, _read_state as read_skill_state, _skill_lock, _state_paths as skill_paths, _write_state as write_skill_state
    # Keep all runtime cache writes on the same binding validated before import.
    account_binding = binding
    rules_directory, rules_state_path, rules_lock_path = rule_paths(project, create=True, binding=account_binding)
    with rule_lock(rules_lock_path):
        rules_state = read_rule_state(rules_state_path, account_binding) if rules_state_path.exists() else empty_rule_state()
        existing_rule_ids = {record["id"] for record in rules_state["rules"]}
        new_rules = []
        for item in legacy_rules:
            copied = dict(item["record"])
            review = copied.get("review")
            if not (copied.get("status") == "active" and isinstance(review, dict)
                    and review.get("decision") == "accept" and current_policy
                    and review.get("policy_digest") == current_policy):
                copied["status"] = "inactive"
            if copied.get("id") not in existing_rule_ids:
                new_rules.append(copied)
        if new_rules:
            rules_state["rules"].extend(new_rules)
            rules_state["revision"] += 1
            write_rule_state(rules_state_path, rules_state)

    skills_directory, skills_state_path, skills_lock_path = skill_paths(project, create=True, binding=account_binding)
    with _skill_lock(skills_lock_path):
        skills_state = read_skill_state(skills_state_path, account_binding) if skills_state_path.exists() else empty_skill_state()
        existing_skill_ids = {record["id"] for record in skills_state["skills"]}
        existing_slugs = {record["slug"] for record in skills_state["skills"]}
        new_skills = []
        for item in legacy_skills:
            copied = dict(item["record"])
            review = copied.get("review")
            still_reviewed = (copied.get("status") == "active" and isinstance(review, dict)
                              and review.get("decision") == "accept" and current_policy
                              and review.get("policy_digest") == current_policy)
            if not still_reviewed:
                copied["status"] = "inactive"
            for file_record in item["files"]:
                relative = PurePosixPath(file_record["path"])
                raw = (Path(binding["versions_root"]) / "legacy" / "skills" / copied["slug"] / relative).read_bytes()
                _write_once(skills_directory.joinpath(copied["slug"], copied["id"], *relative.parts), raw,
                            Path(binding["private_root"]))
            if copied.get("id") not in existing_skill_ids and copied.get("slug") not in existing_slugs:
                new_skills.append(copied)
                existing_slugs.add(copied["slug"])
        if new_skills:
            skills_state["skills"].extend(new_skills)
            skills_state["revision"] += 1
            write_skill_state(skills_state_path, skills_state)

    manifest = {
        "rules": [item["record"].get("id") for item in legacy_rules],
        "skills": [item["record"].get("id") for item in legacy_skills],
    }
    manifest_digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
    claim = append_event(binding, {
        "event_type": "legacy.imported", "category": "legacy", "summary": "Imported confirmed v0.4 rule and skill records additively.",
        "data": {"manifest": manifest, "manifest_digest": manifest_digest, "ownership_confirmed": True,
                 "ownership_evidence": evidence.strip(), "recorded_by": recorded_by.strip()},
    }, event_id=f"legacy-claim-{manifest_digest[:24]}")
    return {"imported": claim["created"], "rules": len(legacy_rules), "skills": len(legacy_skills),
            "manifest_digest": manifest_digest, "event_id": claim["event"]["event_id"]}
