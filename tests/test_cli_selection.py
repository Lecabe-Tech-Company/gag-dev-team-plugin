"""CLI selection delegates to stable releases; no real download or global installs."""
import contextlib
import importlib
import io
import json
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
