"""Verify the instructional policy actually distributed to native clients.

These tests do not classify suite results or simulate an agent's release decision.
"""
import tomllib

from test_project_cli import ProjectCase, ROOT


ROLES = ("gag-desenvolvedor", "gag-documentador", "gag-orquestrador-planejador", "gag-revisor-qa")
SKILLS = ("development-workflow", "sdd-planning", "sdd-development", "sdd-qa")
GUIDANCE_PATHS = ("AGENTS.md", "CLAUDE.md", ".cursor/rules/gag-dev-team.mdc", ".agents/rules/gag-dev-team.md")
LAYOUTS = ((".codex/agents", ".toml"), (".claude/agents", ".md"), (".cursor/agents", ".md"), (".agents/agents", ".md"))
OBSOLETE_VETOES = (
    "falhas, testes obrigatórios não executados ou evidências desatualizadas impedem considerar o pr apto ou enviá-lo",
    "não envie com essa validação pendente ou falhando",
    "falhas ou validação obrigatória pendente impedem o envio",
    "o orquestrador não considera a entrega apta para pr se essa verificação estiver faltando ou falhando",
)


class FeatureTestAcceptanceTests(ProjectCase):
    def assert_release_policy(self, text, requires_criterion=True):
        normalized = " ".join(text.casefold().split())
        if requires_criterion:
            self.assertRegex(normalized, r"todos os testes (?:implementados|novos ou alterados).{0,120}feature.{0,120}(?:passar|aprovad)")
        self.assertRegex(normalized, r"(?:preexistentes|preexistente|anteriores)")
        for obsolete in OBSOLETE_VETOES:
            self.assertNotIn(obsolete, normalized)

    def test_authoritative_skills_template_and_role_copies_share_the_release_scope(self):
        paths = [ROOT / "skills" / skill / "SKILL.md" for skill in SKILLS]
        paths += [ROOT / "skills/sdd-planning/assets/sdd-template.md", ROOT / "AGENTS.md"]
        for path in paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assert_release_policy(path.read_text())
        for role in ROLES:
            source = ROOT / "agents" / (role + ".toml")
            native = ROOT / ".codex/agents" / (role + ".toml")
            with self.subTest(role=role):
                source_text = tomllib.loads(source.read_text())["developer_instructions"]
                native_text = tomllib.loads(native.read_text())["developer_instructions"]
                source_policy = [part for part in source_text.split("\n\n") if "preexistentes" in part.casefold()]
                native_policy = [part for part in native_text.split("\n\n") if "preexistentes" in part.casefold()]
                self.assertEqual(len(source_policy), 1)
                self.assertEqual(source_policy, native_policy)
                self.assert_release_policy(source_text, requires_criterion=role != "gag-documentador")
                self.assert_release_policy(native_text, requires_criterion=role != "gag-documentador")

    def test_qa_instructions_explain_failed_missing_skipped_and_new_regression_cases(self):
        text = (ROOT / "skills/sdd-qa/SKILL.md").read_text().casefold()
        paragraphs = [" ".join(part.split()) for part in text.split("\n\n")]
        self.assertTrue(any("feature" in part and "preexist" in part and
                            any(term in part for term in ("não imped", "não bloque", "pode seguir", "permite seguir", "sem exigir correção"))
                            for part in paragraphs), "Passing feature tests must not inherit a proven legacy failure veto")
        for condition in ("falh", "penden", "omit", "skip"):
            with self.subTest(condition=condition):
                self.assertTrue(any(condition in part and any(term in part for term in ("não", "bloque", "imped"))
                                    for part in paragraphs), "Unverified feature outcomes cannot satisfy acceptance")
        self.assertRegex(text, r"(?:zero testes|ausência de testes|sem testes|descoberta)")
        self.assertTrue(any("regress" in part and any(term in part for term in ("legad", "preexist")) and
                            any(term in part for term in ("não", "corrig", "feature")) for part in paragraphs),
                        "A newly introduced defect must remain in the feature's required coverage")
        self.assertRegex(text, r"(?:revisão|estado) final")

    def test_installation_and_reinstallation_ship_the_policy_to_every_native_client(self):
        runtime = self.install.install(self.project, source=ROOT, harnesses=["codex", "claude", "cursor", "antigravity"])
        self.install.install(self.project, source=ROOT)
        for path in GUIDANCE_PATHS:
            with self.subTest(guidance=path):
                text = (self.project / path).read_text()
                self.assert_release_policy(text)
                for obligation in ("Graphify", "inglês", "QA", "merge automatizado"):
                    self.assertIn(obligation, text)
        for directory, suffix in LAYOUTS:
            for role in ROLES:
                with self.subTest(profile=directory + "/" + role):
                    self.assert_release_policy((self.project / directory / (role + suffix)).read_text(), requires_criterion=role != "gag-documentador")
        for skill in SKILLS:
            relative = "skills/" + skill + "/SKILL.md"
            self.assertEqual((runtime / relative).read_bytes(), (ROOT / relative).read_bytes())
            for directory in (".agents/skills", ".claude/skills", ".cursor/skills"):
                with self.subTest(skill=skill, directory=directory):
                    self.assertEqual((self.project / directory / skill / "SKILL.md").read_bytes(), (ROOT / relative).read_bytes())
