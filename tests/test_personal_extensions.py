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
        self.native = importlib.import_module("native_extensions")
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
        long_slug = "long-" + "a" * 59
        self.assertEqual(len(long_slug), 64)
        with self.subTest(kind="skill", slug_length=64):
            long_files = {**self.files, "SKILL.md": self.files["SKILL.md"].replace("interview-helper", long_slug)}
            long_receipt = self.stage(long_files)
            long_before = self.history_bytes()
            self.assertEqual(self.stage(long_files), long_receipt)
            self.assertEqual(self.history_bytes(), long_before)
        with self.subTest(kind="plugin", slug_length=64):
            manifest = {"plugin.json": json.dumps({"name": long_slug, "version": "1.0.0"})}
            target = long_slug + "@example"
            long_receipt = self.native.stage_plugin(self.binding, self.source, manifest, target, home=self.fake_home)
            long_before = self.history_bytes()
            self.assertEqual(self.native.stage_plugin(self.binding, self.source, manifest, target, home=self.fake_home), long_receipt)
            self.assertEqual(self.history_bytes(), long_before)
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

    def prepare_native(self, harness="codex", binding=None):
        binding = binding or self.binding
        files = {"plugin.json": '{"name":"helper","version":"1.2.3"}',
                 "skills/helper/SKILL.md": "# Helper\nPreserve mandatory review.\n"}
        receipt = self.native.stage_plugin(binding, self.source, files, "helper@example", home=self.fake_home)
        self.extensions.review_extension(binding, receipt["extension_id"], receipt["digest"], self.review, home=self.fake_home)
        profile = self.native.native_profile(binding, harness, self.fake_home)
        reference = {"extension_id": receipt["extension_id"], "content_digest": receipt["digest"]}
        return receipt, profile, reference, files

    def test_native_without_pinned_source_never_calls_installer(self):
        runner = mock.Mock(side_effect=AssertionError("Unreviewed installer must never run"))
        result = self.extensions.install_native_plugin(self.binding, "helper@example", "codex", self.review,
                                                       runner=runner, home=self.fake_home)
        self.assertEqual(result["event"]["data"]["state"], "pending_verification")
        runner.assert_not_called()

    def test_native_unreviewed_or_stale_policy_source_never_calls_installer(self):
        receipt = self.native.stage_plugin(self.binding, self.source,
            {"plugin.json": '{"name":"helper","version":"1.2.3"}'}, "helper@example", home=self.fake_home)
        reference = {"extension_id": receipt["extension_id"], "content_digest": receipt["digest"]}
        runner = mock.Mock(side_effect=AssertionError("An unreviewed installer must never run"))
        with self.assertRaises(self.extensions.PersonalExtensionError):
            self.extensions.install_native_plugin(self.binding, "helper@example", "codex", reference,
                                                   runner=runner, home=self.fake_home)
        self.extensions.review_extension(self.binding, receipt["extension_id"], receipt["digest"], self.review, home=self.fake_home)
        with mock.patch.object(self.native, "policy_snapshot", return_value={"policy_digest": "changed-policy"}):
            with self.assertRaises(self.extensions.PersonalExtensionError):
                self.extensions.install_native_plugin(self.binding, "helper@example", "codex", reference,
                                                       runner=runner, home=self.fake_home)
        runner.assert_not_called()

    def test_native_requires_current_exact_source_review_and_bound_profile(self):
        receipt, profile, reference, _files = self.prepare_native()
        runner = mock.Mock(side_effect=AssertionError("Unbound installer must never run"))
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(self.fake_home / ".codex")}):
            result = self.extensions.install_native_plugin(self.binding, "helper@example", "codex", reference,
                                                           runner=runner, home=self.fake_home)
        self.assertEqual(result["event"]["data"]["state"], "pending_profile")
        runner.assert_not_called()
        with self.subTest(mutation="extra-catalog-file"):
            account_root = self.extensions.profile_root(self.identity, self.fake_home)
            injected = account_root / "catalogs" / receipt["digest"] / "codex/scripts/unreviewed.py"
            injected.parent.mkdir(parents=True)
            injected.write_text("raise RuntimeError('Unreviewed script must never execute')\n", encoding="utf-8")
            original = injected.read_bytes()
            with mock.patch.dict("os.environ", {"CODEX_HOME": str(profile)}), \
                    mock.patch.object(self.native.shutil, "which", return_value="/synthetic/codex"):
                with self.assertRaises(self.extensions.PersonalExtensionError):
                    self.extensions.install_native_plugin(self.binding, "helper@example", "codex", reference,
                                                           runner=runner, home=self.fake_home)
            runner.assert_not_called()
            self.assertEqual(injected.read_bytes(), original)
        bundle = self.version_directory(receipt) / "bundle/plugin.json"
        bundle.write_text('{"name":"unreviewed"}', encoding="utf-8")
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(profile)}):
            with self.assertRaises(self.extensions.PersonalExtensionError):
                self.extensions.install_native_plugin(self.binding, "helper@example", "codex", reference,
                                                       runner=runner, home=self.fake_home)
        runner.assert_not_called()

    def test_native_adapter_states_do_not_claim_activation_or_bypass_trust(self):
        for harness in ("codex", "claude"):
            for returncode, output, state in ((1, {}, "failed"), (1, {"status": "pending_auth"}, "pending_auth"),
                                              (1, {"status": "pending_trust"}, "pending_trust"),
                                              (0, {}, "pending_verification")):
                with self.subTest(harness=harness, state=state):
                    _receipt, profile, reference, _files = self.prepare_native(harness)
                    calls = []
                    def runner(command, **options):
                        calls.append(command)
                        self.assertEqual(options["cwd"], profile)
                        variable = "CODEX_HOME" if harness == "codex" else "CLAUDE_CONFIG_DIR"
                        self.assertEqual(options["env"][variable], str(profile))
                        self.assertFalse(any(key.startswith("GIT_") for key in options["env"]))
                        return subprocess.CompletedProcess(command, returncode, json.dumps(output).encode(), b"")
                    variable = "CODEX_HOME" if harness == "codex" else "CLAUDE_CONFIG_DIR"
                    with mock.patch.object(self.native.shutil, "which", return_value="/synthetic/host"), \
                            mock.patch.dict("os.environ", {variable: str(profile)}):
                        result = self.extensions.install_native_plugin(self.binding, "helper@example", harness,
                                                                       reference, runner=runner, home=self.fake_home)
                    data = result["event"]["data"]
                    self.assertEqual(data["state"], state)
                    self.assertFalse(data["activation_verified"])
                    self.assertFalse(any(value in command for command in calls for value in ("--yes", "--force", "--skip-trust")))
                    if harness == "claude" and len(calls) == 2:
                        self.assertEqual(calls[1][calls[1].index("--scope") + 1], "user")

    def test_native_malformed_success_is_unverified(self):
        _receipt, profile, reference, _files = self.prepare_native()
        def runner(command, **options):
            return subprocess.CompletedProcess(command, 0, b"not-json", b"")
        with mock.patch.object(self.native.shutil, "which", return_value="/synthetic/codex"), \
                mock.patch.dict("os.environ", {"CODEX_HOME": str(profile)}):
            result = self.extensions.install_native_plugin(self.binding, "helper@example", "codex", reference,
                                                           runner=runner, home=self.fake_home)
        self.assertEqual(result["event"]["data"]["state"], "pending_verification")
        self.assertFalse(result["event"]["data"]["activation_verified"])

    def test_native_success_uses_only_pinned_local_catalog_and_preserves_actual_bytes(self):
        receipt, profile, reference, files = self.prepare_native()
        calls = []
        before = self.history_bytes()
        original_profile = self.fake_home / ".codex"
        original_profile.mkdir()
        old_file = original_profile / "user-settings"
        old_file.write_text("Preserve existing native profile.", encoding="utf-8")
        def runner(command, **options):
            calls.append(command)
            if "marketplace" in command:
                catalog = Path(command[4])
                self.assertTrue(catalog.is_relative_to(self.extensions.profile_root(self.identity, self.fake_home)))
                self.assertEqual((catalog / "plugins/helper/plugin.json").read_text(), files["plugin.json"])
                return subprocess.CompletedProcess(command, 0, b"{}", b"")
            self.assertNotIn("helper@example", command)
            target = command[3]
            marketplace = target.split("@")[1]
            source = profile / "plugins/cache" / marketplace / "helper/1.2.3"
            source.mkdir(parents=True)
            for name, content in files.items():
                destination = source / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, json.dumps({"installedPath": str(source), "version": "1.2.3"}).encode(), b"")
        with mock.patch.object(self.native.shutil, "which", return_value="/synthetic/codex"), \
                mock.patch.dict("os.environ", {"CODEX_HOME": str(profile)}):
            result = self.extensions.install_native_plugin(self.binding, "helper@example", "codex", reference,
                                                           runner=runner, home=self.fake_home)
        data = result["event"]["data"]
        self.assertEqual(data["state"], "pending_restart")
        self.assertFalse(data["activation_verified"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(old_file.read_text(), "Preserve existing native profile.")
        self.assert_history_preserved(before)
        self.assertEqual((self.version_directory(receipt) / "bundle/plugin.json").read_text(), files["plugin.json"])

    def test_native_accounts_cannot_share_host_profile_or_load_plugin_as_skill(self):
        receipt, profile, reference, _files = self.prepare_native()
        other = self.binding_for(202, "second-user")
        _other_receipt, other_profile, other_reference, _files = self.prepare_native(binding=other)
        self.assertNotEqual(profile, other_profile)
        marker_before = (profile / "account.json").read_bytes()
        runner = mock.Mock(side_effect=AssertionError("Another account's native profile must never run"))
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(profile)}):
            result = self.extensions.install_native_plugin(other, "helper@example", "codex", other_reference,
                                                           runner=runner, home=self.fake_home)
        self.assertEqual(result["event"]["data"]["state"], "pending_profile")
        runner.assert_not_called()
        self.assertEqual((profile / "account.json").read_bytes(), marker_before)
        with self.assertRaises(self.extensions.PersonalExtensionError):
            self.extensions.activate_skill(self.binding, receipt["extension_id"], receipt["digest"], home=self.fake_home)
        with self.assertRaises(self.extensions.PersonalExtensionError):
            self.extensions.load_personal_skill(self.binding, receipt["extension_id"], receipt["digest"], home=self.fake_home)

    def test_native_unsupported_mandatory_target_and_missing_host(self):
        for target, harness in (("gag-dev-team@example", "codex"), ("helper@example", "cursor")):
            with self.assertRaises(self.extensions.PersonalExtensionError):
                self.extensions.install_native_plugin(self.binding, target, harness, self.review, home=self.fake_home)
        _receipt, profile, reference, _files = self.prepare_native()
        with mock.patch.object(self.native.shutil, "which", return_value=None), \
                mock.patch.dict("os.environ", {"CODEX_HOME": str(profile)}):
            result = self.extensions.install_native_plugin(self.binding, "helper@example", "codex", reference, home=self.fake_home)
        self.assertEqual(result["event"]["data"]["state"], "pending_host")
