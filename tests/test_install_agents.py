"""Instalação de agentes preserva configurações e funciona sem iniciar modelos."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_agents", ROOT / "scripts/install-agents.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class AgentInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)

    def test_installs_profiles_and_repeated_install_is_idempotent(self):
        target = installer.install(self.project)
        originals = {p.name: p.read_bytes() for p in (ROOT / "agents").glob("gag-*.toml")}
        self.assertEqual({p.name: p.read_bytes() for p in target.glob("*.toml")}, originals)
        self.assertEqual(installer.install(self.project), target)

    def test_conflict_preserves_existing_file_and_does_not_partially_install(self):
        target = self.project / ".codex/agents"
        target.mkdir(parents=True)
        existing = target / "gag-documentador.toml"
        existing.write_text("custom = true\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            installer.install(self.project)
        self.assertEqual(existing.read_text(), "custom = true\n")
        self.assertEqual(list(target.iterdir()), [existing])

    def test_unknown_project_is_not_created(self):
        with self.assertRaises(FileNotFoundError):
            installer.install(self.project / "missing")

    def test_external_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            link = self.project / ".codex"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Ambiente não permite symlinks")
            with self.assertRaises(ValueError):
                installer.install(self.project)
            self.assertEqual(list(Path(outside).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
