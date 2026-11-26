"""Verify configuration classification against committed Git blobs and modes."""
import json
import unittest
from pathlib import Path

import test_english_gate as english_tests


class ConfigurationLanguageGateTests(unittest.TestCase):
    setUp = english_tests.EnglishGateTests.setUp
    git = english_tests.EnglishGateTests.git
    write = english_tests.EnglishGateTests.write
    commit = english_tests.EnglishGateTests.commit
    analyze = english_tests.EnglishGateTests.analyze

    def fake_run(self, arguments, **options):
        if arguments[0] == self.graphify_binary:
            corpus = Path(arguments[2])
            self.exported_paths.extend(
                str(path.relative_to(corpus)) for path in corpus.rglob("*") if path.is_file()
            )
        return english_tests.EnglishGateTests.fake_run(self, arguments, **options)

    def commit_mode(self, files, executable):
        for relative, content in files.items():
            self.write(relative, content)
            (self.root / relative).chmod(0o755 if executable else 0o644)
        self.git("add", ".")
        self.git("commit", "-qm", "configuration fixture")
        for relative in files:
            self.assertTrue(self.git("ls-tree", "HEAD", "--", relative).startswith(
                "100755" if executable else "100644"
            ))
        self.exported_paths = []

    def assert_configuration_modes_are_skipped(self, relative, content):
        files = {relative: content}
        for executable in (False, True):
            with self.subTest(executable=executable):
                self.commit_mode(files, executable)
                self.analyze()
                record = json.loads((self.root / "graphify-out/pr-check/prod/check.json").read_text())
                self.assertEqual(set(record["skipped"]), set(files))
                self.assertEqual(record["language"]["checked"], [])
                self.assertEqual(record["analyzed"], [])
                self.assertEqual(record["language"]["result"], "passed")
                self.assertIsNone(record["graph"])
                self.assertEqual(self.graphify_calls, 0)
                self.assertEqual(self.exported_paths, [])

    def test_environment_is_skipped_with_either_committed_mode(self):
        self.assert_configuration_modes_are_skipped(
            ".env.example", '# Configuração sintética\r\nAPP_NAME="Produção"\r\n'
            "DB_CONNECTION=pgsql\r\nPEDIDO_TOTAL=2\r\nEMPTY=\r\n"
            "MAIL_NAME='${APP_NAME}'\r\n"
        )

    def test_composer_lock_is_skipped_with_either_committed_mode(self):
        self.assert_configuration_modes_are_skipped(
            "composer.lock", json.dumps({
                "packages": [{"name": "vendor/pacote", "description": "Produção"}],
                "packages-dev": [], "content-hash": "synthetic",
            }) + "\n"
        )

    def test_configuration_does_not_hide_invalid_code_in_the_same_pr(self):
        self.commit_mode({".env.example": "APP_NAME=Example\nDB_CONNECTION=pgsql\n",
                          "composer.lock": '{"packages": []}\n',
                          "orders.py": "pedido = 1\n"}, True)
        with self.assertRaises(self.hook.GateError) as denied:
            self.analyze()
        self.assertIn("orders.py", str(denied.exception))
        self.assertIn("pedido", str(denied.exception))
        self.assertEqual(self.graphify_calls, 0)

    def test_configuration_never_enters_the_graphify_corpus(self):
        self.commit_mode({".env.example": "APP_NAME=Example\nDB_CONNECTION=pgsql\n",
                          "composer.lock": '{"packages": []}\n',
                          "orders.py": "order_count = 1\n"}, True)
        self.analyze()
        self.assertEqual(self.exported_paths, ["orders.py"])
        record = json.loads((self.root / "graphify-out/pr-check/prod/check.json").read_text())
        self.assertEqual(record["language"]["checked"], ["orders.py"])

    def test_code_extensions_and_shebangs_take_precedence_over_config_names(self):
        cases = {
            ".env.example.php": "<?php $pedido = 1;\n",
            ".env.example.sh": "pedido=1\n",
            ".env.example": "#!/bin/sh\npedido=1\n",
            "composer.lock": "#!/usr/bin/env python3\npedido = 1\n",
        }
        for relative, source in cases.items():
            with self.subTest(path=relative):
                self.commit_mode({relative: source}, False)
                with self.assertRaises(self.hook.GateError) as denied:
                    self.analyze()
                self.assertIn(relative, str(denied.exception))
                self.assertEqual(self.graphify_calls, 0)
                self.git("rm", relative)
                self.git("commit", "-qm", "remove script fixture")

    def test_similar_and_generic_example_names_do_not_gain_config_exemption(self):
        for relative in (".environment", ".envexample", "settings.example", "composer.locked"):
            with self.subTest(path=relative):
                self.commit_mode({relative: "PEDIDO_TOTAL=1\n"}, False)
                with self.assertRaises(self.hook.GateError) as denied:
                    self.analyze()
                self.assertIn(relative, str(denied.exception))
                self.assertEqual(self.graphify_calls, 0)
                self.git("rm", relative)
                self.git("commit", "-qm", "remove unknown fixture")

    def test_configuration_does_not_hide_a_code_parser_failure(self):
        self.commit_mode({".env.example": "APP_NAME=Example\n",
                          "orders.py": "def calculate_total(:\n    return 1\n"}, True)
        with self.assertRaises(self.hook.GateError) as denied:
            self.analyze()
        self.assertIn("orders.py", str(denied.exception))
        self.assertEqual(self.graphify_calls, 0)
