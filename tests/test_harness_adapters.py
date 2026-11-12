"""ESP-066 v2 selected native adapters; no clients or external services."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
LAYOUTS = {"codex": (".codex/agents", ".toml"), "claude": (".claude/agents", ".md"), "cursor": (".cursor/agents", ".md"), "antigravity": (".agents/agents", ".md")}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gag adapters qa ")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.installer = importlib.import_module("project_install")

    def snapshot(self):
        return {str(path.relative_to(self.project)): path.read_bytes() for path in self.project.rglob("*") if path.is_file() and ".git" not in path.parts}

    def test_each_selection_installs_only_its_native_agents(self):
        for chosen in LAYOUTS:
            with self.subTest(chosen=chosen), tempfile.TemporaryDirectory(prefix="gag single adapter ") as temp:
                project = Path(temp)
                subprocess.run(["git", "init", "-q", str(project)], check=True)
                self.installer.install(project, source=ROOT, harnesses=[chosen], release_tag="v0.3.0")
                for harness, (directory, extension) in LAYOUTS.items():
                    profiles = list((project / directory).glob("gag-*" + extension))
                    self.assertEqual(len(profiles), 5 if harness == chosen else 0)
                manifest = json.loads((project / ".gag-dev-team/install.json").read_text())
                self.assertEqual(manifest["harnesses"], [chosen])
                self.assertEqual(manifest["release_tag"], "v0.3.0")

    def test_multiselection_reuses_selection_and_release_on_plain_reinstall(self):
        chosen = ["claude", "cursor", "antigravity"]
        self.installer.install(self.project, source=ROOT, harnesses=chosen, release_tag="v0.3.0")
        before = self.snapshot()
        self.installer.install(self.project, source=ROOT)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.project / ".codex").exists())

    def test_unknown_or_empty_selection_refuses_without_writing(self):
        for selection in ([], ["unknown"], ["codex", "unknown"]):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.installer.install(self.project, source=ROOT, harnesses=selection)
        self.assertEqual(self.snapshot(), {})

    def test_claude_native_root_and_user_settings_are_preserved(self):
        path = self.project / ".claude/settings.json"
        path.parent.mkdir()
        own_hook = {"hooks": [{"type": "command", "command": "echo custom-hook"}]}
        path.write_text(json.dumps({"permissions": {"allow": ["Read"]}, "hooks": {"SessionStart": [own_hook]}}))
        self.installer.install(self.project, source=ROOT, harnesses=["claude"])
        config = json.loads(path.read_text())
        self.assertEqual(config["agent"], "gag-orquestrador-planejador")
        self.assertEqual(config["model"], "sonnet")
        self.assertEqual(config["permissions"], {"allow": ["Read"]})
        self.assertIn(own_hook, config["hooks"]["SessionStart"])
        self.assertTrue(all(event in config["hooks"] for event in ("SessionStart", "Stop", "PreToolUse")))

    def test_conflict_in_one_selected_adapter_prevents_partial_install(self):
        conflict = self.project / ".cursor/agents/gag-documentador.md"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("customized agent\n")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.installer.install(self.project, source=ROOT, harnesses=["claude", "cursor"])
        self.assertEqual(self.snapshot(), before)

    def test_codex_bootstrap_helper_is_portable_and_runs_from_nested_cwd(self):
        runtime = self.installer.install(self.project, source=ROOT, harnesses=["codex"])
        self.installer.configure_scripta(self.project, "qa-portable-token-not-real")
        config = tomllib.loads((self.project / ".codex/config.toml").read_text())
        command = config["mcp_servers"]["docs"]["http_headers_helper"]
        self.assertNotIn(str(ROOT), command)
        self.assertNotIn(str(self.project), command)
        self.assertNotIn(sys.executable, command)
        nested = self.project / "nested/folder with spaces"
        nested.mkdir(parents=True)
        result = subprocess.run(command, shell=True, cwd=nested, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"Authorization": "Bearer qa-portable-token-not-real"})
        self.assertEqual(result.stderr, "")


    def test_native_approval_events_route_to_canonical_prompt_handler(self):
        self.installer.install(self.project, source=ROOT, harnesses=list(LAYOUTS))
        configs = [(".codex/hooks.json", "UserPromptSubmit", "hooks"),
                   (".claude/settings.json", "UserPromptSubmit", "hooks"),
                   (".cursor/hooks.json", "beforeSubmitPrompt", "hooks"),
                   (".agents/hooks.json", "PreInvocation", "gag-dev-team")]
        for path, event, container in configs:
            config = json.loads((self.project / path).read_text())
            with self.subTest(path=path):
                self.assertIn(event, config[container])
                self.assertIn("UserPromptSubmit", json.dumps(config[container][event]))

    def test_role_model_aliases_and_antigravity_effort_are_native(self):
        self.installer.install(self.project, source=ROOT, harnesses=["claude", "antigravity"])
        aliases = {"gag-orquestrador-planejador": ("sonnet", "pro"), "gag-desenvolvedor": ("haiku", "flash"), "gag-investigador-advisor": ("opus", "pro"), "gag-revisor-qa": ("opus", "pro"), "gag-documentador": ("haiku", "flash")}
        for role, (claude_model, antigravity_model) in aliases.items():
            claude = (self.project / ".claude/agents" / (role + ".md")).read_text().split("---", 2)[1]
            anti = (self.project / ".agents/agents" / (role + ".md")).read_text().split("---", 2)[1]
            with self.subTest(role=role):
                self.assertIn('model: "' + claude_model + '"', claude)
                self.assertIn('model: "' + antigravity_model + '"', anti)
                self.assertNotIn("effort:", anti)
                if claude_model == "haiku":
                    self.assertNotIn("effort:", claude)

if __name__ == "__main__":
    unittest.main()
