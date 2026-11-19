"""Synthetic authenticated identities and isolated Git/profile roots for environment QA."""
import importlib
import json
from pathlib import Path
import subprocess
import tempfile

from test_project_cli import ProjectCase


class EnvironmentCase(ProjectCase):
    def setUp(self):
        super().setUp()
        self.git("config", "user.name", "Synthetic Git Author")
        self.git("config", "user.email", "synthetic-author@example.invalid")
        (self.project / "README.md").write_text("# Synthetic environment project\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "base")
        self.identity_module = importlib.import_module("environment_identity")
        self.event_store = importlib.import_module("event_store")
        self.projection = importlib.import_module("environment_projection")
        self.identity = self.resolve_fake_identity()
        self.binding = self.identity_module.project_binding(self.project, self.identity)
        self.profile_temp = tempfile.TemporaryDirectory(prefix="synthetic-personal-home-")
        self.addCleanup(self.profile_temp.cleanup)
        self.fake_home = Path(self.profile_temp.name)

    def git(self, *arguments, cwd=None):
        return subprocess.check_output(["git", *arguments], cwd=cwd or self.project,
                                       stderr=subprocess.DEVNULL).decode("utf-8").strip()

    def resolve_fake_identity(self, account_id=101, login="qa-first", host="github.com"):
        def runner(command, **options):
            self.assertEqual(command, ["gh", "api", "user", "--hostname", host])
            self.assertTrue(options.get("capture_output"))
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"id": account_id, "login": login}).encode("utf-8"), stderr=b"")

        return self.identity_module.resolve_identity(host, runner=runner)

    def binding_for(self, account_id, login, project=None):
        identity = self.resolve_fake_identity(account_id, login)
        return self.identity_module.project_binding(project or self.project, identity)

    def history_bytes(self, binding=None):
        selected = binding or self.binding
        private_root = Path(selected["private_root"])
        return {path.relative_to(private_root).as_posix(): path.read_bytes()
                for name in ("events", "versions") for path in (private_root / name).rglob("*")
                if path.is_file() and not path.is_symlink()}

    def assert_history_preserved(self, before, binding=None):
        after = self.history_bytes(binding)
        for name, content in before.items():
            self.assertIn(name, after)
            self.assertEqual(after[name], content, name)
