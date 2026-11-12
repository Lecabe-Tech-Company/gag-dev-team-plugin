"""CLI selection delegates to stable releases; no real download or global installs."""
import contextlib
import importlib
import io
import json
import subprocess
import sys
from unittest.mock import Mock, patch

from test_project_cli import ProjectCase


class CliSelectionTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.cli = importlib.import_module("gag_dev_team")

    def test_interactive_first_install_accepts_multiple_numbers_and_deduplicates(self):
        stdin = Mock()
        stdin.isatty.return_value = True
        with patch.object(sys, "stdin", stdin), patch("builtins.input", return_value="1, 2,4,2"), contextlib.redirect_stdout(io.StringIO()):
            selected = self.cli.choose_harnesses(self.project, None)
        self.assertEqual(selected, ["codex", "claude", "antigravity"])
        self.assertFalse((self.project / ".gag-dev-team").exists())

    def test_explicit_names_support_comma_repeated_options_and_case(self):
        self.assertEqual(self.cli.choose_harnesses(self.project, ["Codex,Claude", "cursor,codex"]), ["codex", "claude", "cursor"])

    def test_plain_reinstall_reuses_recorded_selection_without_prompt(self):
        state = self.project / ".gag-dev-team/install.json"
        state.parent.mkdir()
        state.write_text(json.dumps({"harnesses": ["claude", "cursor"]}))
        with patch("builtins.input", side_effect=AssertionError("must not prompt")):
            self.assertEqual(self.cli.choose_harnesses(self.project, None), ["claude", "cursor"])

    def test_first_install_noninteractive_requires_explicit_selection(self):
        stdin = Mock()
        stdin.isatty.return_value = False
        with patch.object(sys, "stdin", stdin), patch("releases.install_latest") as latest, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                self.cli.main(["install", "--project", str(self.project)])
        self.assertEqual(caught.exception.code, 1)
        latest.assert_not_called()
        self.assertFalse((self.project / ".gag-dev-team").exists())

    def test_invalid_interactive_selection_never_falls_back_to_default(self):
        stdin = Mock()
        stdin.isatty.return_value = True
        for answer in ("", "0", "5", "1,unknown"):
            with self.subTest(answer=answer), patch.object(sys, "stdin", stdin), patch("builtins.input", return_value=answer), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(ValueError):
                    self.cli.choose_harnesses(self.project, None)

    def test_install_command_fetches_stable_release_with_exact_selection(self):
        runtime = self.project / ".gag-dev-team/plugin"
        with patch("releases.install_latest", return_value=runtime) as latest, patch.object(self.cli, "install", side_effect=AssertionError("local branch fallback is forbidden")), contextlib.redirect_stdout(io.StringIO()):
            self.cli.main(["install", "--project", str(self.project), "--harness", "claude,cursor"])
        latest.assert_called_once_with(str(self.project), harnesses=["claude", "cursor"])

    def test_cli_records_existing_contextual_consent_without_prompt_or_prior_declaration(self):
        stdin = Mock()
        stdin.isatty.return_value = True
        evidence = "Pode corrigir o SDD apresentado."
        with patch.object(sys, "stdin", stdin), patch("builtins.input", side_effect=AssertionError("do not ask for repeated approval")), contextlib.redirect_stdout(io.StringIO()):
            self.cli.main(["approve-sdd", "--project", str(self.project), "--reference", "ESP-QA", "--sdd-version", "24", "--evidence", evidence, "--recorded-by", "orquestrador"])
        path = self.project / ".gag-dev-team/sdd.json"
        state = json.loads(path.read_text())
        self.assertEqual(subprocess.run(["git", "check-ignore", "-q", "--", ".gag-dev-team/sdd.json"], cwd=self.project).returncode, 0)
        self.assertIs(state["approved"], True)
        self.assertEqual(state["reference"], "ESP-QA")
        self.assertEqual(state["version"], "24")
        self.assertEqual(state["evidence"], evidence)
        self.assertEqual(state["recorded_by"], "orquestrador")
        before = path.read_bytes()
        output = io.StringIO()
        with patch("builtins.input", side_effect=AssertionError("no approval ceremony")), contextlib.redirect_stdout(output):
            self.cli.main(["declare-sdd", "--project", str(self.project), "--reference", "ESP-QA", "--sdd-version", "24"])
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("aguarde", output.getvalue().lower())

    def test_cli_missing_evidence_does_not_prompt_or_invent_consent(self):
        stdin = Mock()
        stdin.isatty.return_value = True
        with patch.object(sys, "stdin", stdin), patch("builtins.input", side_effect=AssertionError("no literal-prompt fallback")), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                self.cli.main(["approve-sdd", "--project", str(self.project), "--reference", "ESP-QA", "--sdd-version", "24", "--recorded-by", "orquestrador"])
        self.assertNotEqual(caught.exception.code, 0)
        self.assertFalse((self.project / ".gag-dev-team/sdd.json").exists())

    def test_cli_legacy_confirm_supports_manual_confirmation_before_declaration(self):
        with patch("builtins.input", side_effect=AssertionError("explicit terminal flag must not ask again")), contextlib.redirect_stdout(io.StringIO()):
            self.cli.main(["approve-sdd", "--project", str(self.project), "--reference", "ESP-QA", "--sdd-version", "24", "--confirm"])
        state = json.loads((self.project / ".gag-dev-team/sdd.json").read_text())
        self.assertIs(state["approved"], True)
        self.assertEqual(state["approval_source"], "terminal-confirmation")
        self.assertNotIn("evidence", state)
