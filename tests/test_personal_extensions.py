"""Private extension lifecycle, immutable content, and native adapter boundaries."""
import importlib
import json
from pathlib import Path
import subprocess
from unittest import mock

from environment_fixtures import EnvironmentCase


class PersonalExtensionTests(EnvironmentCase):
    def setUp(self):
        super().setUp()
        self.extensions = importlib.import_module("personal_extensions")
        self.source = {"repository": "example/skills", "commit": "a" * 40}
        self.files = {"SKILL.md": "---\nname: interview-helper\ndescription: Ask focused questions.\n---\nAsk one question at a time.\n",
                      "references/questions.md": "Use a focused interview.\n"}
        self.review = {"policy_digest": self.extensions.policy_snapshot()["policy_digest"],
                       "decision": "accept", "reviewer": "synthetic-qa", "reason": "Preserves mandatory policy."}

    def stage(self, files=None):
        return self.extensions.stage_skill(self.binding, self.source, files or self.files, home=self.fake_home)

    def version_directory(self, receipt):
        return self.extensions.profile_root(self.identity, self.fake_home) / "extensions" / receipt["extension_id"] / "versions" / receipt["digest"]

    def activate(self, receipt):
        arguments = (self.binding, receipt["extension_id"], receipt["digest"])
        self.extensions.review_extension(*arguments, self.review, home=self.fake_home)
        self.extensions.activate_skill(*arguments, home=self.fake_home)
        return arguments

    def test_download_is_inert_until_current_accepting_review_and_activation(self):
        receipt = self.stage()
        arguments = (self.binding, receipt["extension_id"], receipt["digest"])
        for operation in (self.extensions.activate_skill, self.extensions.load_personal_skill):
            with self.assertRaises(self.extensions.PersonalExtensionError):
                operation(*arguments, home=self.fake_home)
        self.activate(receipt)
        loaded = self.extensions.load_personal_skill(*arguments, home=self.fake_home)
        self.assertEqual(loaded["files"], self.files)
        self.assertEqual(loaded["priority"], "below-mandatory-plugin-policy")
        self.assertEqual(self.git("ls-files"), "README.md")
        self.git("add", ".")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")

    def test_retries_versions_and_deactivation_preserve_all_prior_bytes(self):
        first = self.stage()
        before = self.history_bytes()
        self.assertEqual(self.stage()["digest"], first["digest"])
        self.assert_history_preserved(before)
        old_files = {str(path): path.read_bytes() for path in self.version_directory(first).rglob("*") if path.is_file()}
        second = self.stage({**self.files, "references/questions.md": "Ask a second focused question.\n"})
        self.assertNotEqual(first["digest"], second["digest"])
        self.activate(second)
        before = self.history_bytes()
        self.event_store.append_event(self.binding, {"event_type": "extension.deactivated", "data": {
            "extension_id": second["extension_id"], "digest": second["digest"], "state": "inactive"}})
        self.assert_history_preserved(before)
        for name, content in old_files.items():
            self.assertEqual(Path(name).read_bytes(), content)
        with self.assertRaises(self.extensions.PersonalExtensionError):
            self.extensions.load_personal_skill(self.binding, second["extension_id"], second["digest"], home=self.fake_home)

    def test_changed_or_extra_bundle_files_cannot_load(self):
        for mutation in ("changed", "extra", "symlink"):
            with self.subTest(mutation=mutation):
                receipt = self.stage()
                arguments = self.activate(receipt)
                bundle = self.version_directory(receipt) / "bundle"
                if mutation == "changed":
                    target = bundle / "SKILL.md"
                    original = target.read_bytes()
                    target.write_text("Unreviewed instructions", encoding="utf-8")
                else:
                    target = bundle / "unreviewed.sh"
                    if mutation == "symlink":
                        target.symlink_to(bundle / "SKILL.md")
                    else:
                        target.write_text("echo unreviewed", encoding="utf-8")
                try:
                    with self.assertRaises(self.extensions.PersonalExtensionError):
                        self.extensions.load_personal_skill(*arguments, home=self.fake_home)
                finally:
                    if mutation == "changed":
                        target.write_bytes(original)
                    else:
                        target.unlink()

    def test_source_credentials_paths_and_executables_rejected_before_storage(self):
        for source in ({**self.source, "token": "synthetic-secret"},
                       {**self.source, "repository": "https://secret@example.com/org/repo"},
                       {**self.source, "host": "other.example"},
                       {**self.source, "ref": "user:password"}):
            with self.subTest(source=source):
                with self.assertRaises(self.extensions.PersonalExtensionError):
                    self.extensions.stage_skill(self.binding, source, self.files, self.fake_home)
        for name in ("../escape.md", "scripts/run.sh", "/absolute.md"):
            with self.subTest(name=name):
                with self.assertRaises(self.extensions.PersonalExtensionError):
                    self.stage({**self.files, name: "echo never"})
        self.assertFalse((self.fake_home / ".local").exists())

    def test_account_isolation_login_rename_and_git_profile_rejection(self):
        root = self.extensions.profile_root(self.identity, self.fake_home)
        renamed = {**self.identity, "login": "renamed-user"}
        self.assertEqual(self.extensions.profile_root(renamed, self.fake_home), root)
        other = self.resolve_fake_identity(202, "second-user")
        self.assertNotEqual(self.extensions.profile_root(other, self.fake_home), root)
        with self.assertRaises(self.extensions.PersonalExtensionError):
            self.extensions.profile_root(self.identity, self.project)

    def test_symbolic_home_cannot_redirect_personal_storage(self):
        alias = self.fake_home / "home-alias"
        destination = self.fake_home / "actual-home"
        destination.mkdir()
        alias.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(self.extensions.PersonalExtensionError):
            self.extensions.profile_root(self.identity, alias)
        self.assertEqual(list(destination.iterdir()), [])

    def test_native_adapter_states_do_not_claim_activation_or_bypass_trust(self):
        for harness in ("codex", "claude"):
            for returncode, output, state in ((1, {}, "failed"), (1, {"status": "pending_auth"}, "pending_auth"),
                                              (1, {"status": "pending_trust"}, "pending_trust"),
                                              (0, {}, "pending_verification")):
                with self.subTest(harness=harness, state=state):
                    calls = []
                    def runner(command, **options):
                        calls.append(command)
                        return subprocess.CompletedProcess(command, returncode, json.dumps(output).encode(), b"")
                    with mock.patch.object(self.extensions.shutil, "which", return_value="/synthetic/host"):
                        result = self.extensions.install_native_plugin(self.binding, "helper@example", harness,
                                                                       self.review, runner=runner, home=self.fake_home)
                    data = result["event"]["data"]
                    self.assertEqual(data["state"], state)
                    self.assertFalse(data["activation_verified"])
                    self.assertFalse(any(value in calls[0] for value in ("--yes", "--force", "--skip-trust")))
                    if harness == "claude":
                        self.assertEqual(calls[0][calls[0].index("--scope") + 1], "user")

    def test_native_malformed_success_is_unverified(self):
        def runner(command, **options):
            return subprocess.CompletedProcess(command, 0, b"not-json", b"")
        with mock.patch.object(self.extensions.shutil, "which", return_value="/synthetic/codex"):
            result = self.extensions.install_native_plugin(self.binding, "helper@example", "codex", self.review,
                                                           runner=runner, home=self.fake_home)
        self.assertEqual(result["event"]["data"]["state"], "pending_verification")
        self.assertFalse(result["event"]["data"]["activation_verified"])

    def test_native_success_retains_actual_version_bytes_without_claiming_active(self):
        source = self.fake_home / ".codex/plugins/cache/example/helper/1.2.3"
        source.mkdir(parents=True)
        (source / "plugin.json").write_text('{"name":"helper","version":"1.2.3"}', encoding="utf-8")
        def runner(command, **options):
            return subprocess.CompletedProcess(command, 0, json.dumps({"installedPath": str(source), "version": "1.2.3"}).encode(), b"")
        with mock.patch.object(self.extensions.shutil, "which", return_value="/synthetic/codex"):
            result = self.extensions.install_native_plugin(self.binding, "helper@example", "codex", self.review,
                                                           runner=runner, home=self.fake_home)
        data = result["event"]["data"]
        self.assertEqual(data["state"], "pending_restart")
        self.assertTrue(data["retained"])
        self.assertFalse(data["activation_verified"])
        retained = self.extensions.profile_root(self.identity, self.fake_home) / "extensions" / data["extension_id"] / "versions" / data["digest"] / "bundle/plugin.json"
        self.assertEqual(retained.read_bytes(), (source / "plugin.json").read_bytes())

    def test_native_unsupported_mandatory_target_and_missing_host(self):
        for target, harness in (("gag-dev-team@example", "codex"), ("helper@example", "cursor")):
            with self.assertRaises(self.extensions.PersonalExtensionError):
                self.extensions.install_native_plugin(self.binding, target, harness, self.review, home=self.fake_home)
        with mock.patch.object(self.extensions.shutil, "which", return_value=None):
            result = self.extensions.install_native_plugin(self.binding, "helper@example", "codex", self.review, home=self.fake_home)
        self.assertEqual(result["event"]["data"]["state"], "pending_host")

