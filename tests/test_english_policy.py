"""English code policy distribution without imposing English on planning."""
import json
import tomllib

from test_project_cli import ProjectCase, ROOT


class EnglishPolicyTests(ProjectCase):
    def test_every_native_entry_point_preserves_the_language_boundary(self):
        self.install.install(self.project, source=ROOT,
                             harnesses=["codex", "claude", "cursor", "antigravity"])
        entry_points = (
            "AGENTS.md", "CLAUDE.md", ".cursor/rules/gag-dev-team.mdc",
            ".agents/rules/gag-dev-team.md",
        )
        for relative in entry_points:
            with self.subTest(path=relative):
                guidance = (self.project / relative).read_text(encoding="utf-8").casefold()
                for concept in ("código", "inglês", "classes", "variáveis", "frontend",
                                "planejamento", "documentação", "português", "bloque"):
                    self.assertIn(concept, guidance)
        manifest = json.loads((self.project / ".gag-dev-team/install.json").read_text())
        self.assertEqual(manifest["harnesses"], ["codex", "claude", "cursor", "antigravity"])

    def test_native_codex_roles_include_the_code_policy(self):
        self.install.install(self.project, source=ROOT, harnesses=["codex"])
        roles = list((self.project / ".codex/agents").glob("gag-*.toml"))
        self.assertEqual(len(roles), 5)
        for path in roles:
            with self.subTest(role=path.stem):
                profile = tomllib.loads(path.read_text(encoding="utf-8"))
                instructions = profile["developer_instructions"].casefold()
                self.assertIn("código", instructions)
                self.assertIn("inglês", instructions)
                self.assertIn("planejamento", instructions)
                self.assertIn("português", instructions)
