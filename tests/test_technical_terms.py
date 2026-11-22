"""Technical vocabulary is explicit, reloadable, and required by the language gate."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("technical_policy", ROOT / "hooks/scripts/english_code.py")
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class TechnicalTermsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="technical terms qa ")
        self.addCleanup(self.temp.cleanup)
        self.terms_file = Path(self.temp.name) / "technical_terms.json"
        self.terms_file.write_text(json.dumps({"terms": ["kpis"]}), encoding="utf-8")
        self.patch = patch.object(policy, "TECHNICAL_TERMS_FILE", self.terms_file)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def verify(self, source):
        return policy.validate_changes([{
            "path": "metrics.py",
            "content": source,
            "added_lines": set(range(1, source.count("\n") + 2)),
            "path_changed": True,
        }])

    def test_registered_acronym_is_accepted_inside_an_identifier(self):
        self.assertEqual(self.verify("def calculate_kpis():\n    return 1\n"), [])

    def test_registering_one_token_does_not_allow_unknown_identifier_parts(self):
        diagnostics = self.verify("def calculate_kpis_quantidade():\n    return 1\n")
        self.assertEqual(len(diagnostics), 1, diagnostics)
        self.assertIn("'quantidade'", diagnostics[0])
        self.assertIn("metrics.py:1:", diagnostics[0])

    def test_prefixes_and_word_parts_are_not_registered_by_an_exact_token(self):
        diagnostics = self.verify("def calculate_xkpisx():\n    return 1\n")
        self.assertEqual(len(diagnostics), 1, diagnostics)
        self.assertIn("'xkpisx'", diagnostics[0])

    def test_removed_term_is_not_retained_by_dictionary_cache(self):
        self.assertEqual(self.verify("def calculate_kpis():\n    return 1\n"), [])
        self.terms_file.write_text(json.dumps({"terms": []}), encoding="utf-8")
        diagnostics = self.verify("def calculate_kpis():\n    return 1\n")
        self.assertTrue(any("'kpis'" in item for item in diagnostics), diagnostics)

    def test_missing_terms_file_blocks_even_valid_english_code(self):
        self.terms_file.unlink()
        with self.assertRaises(policy.LanguageCheckError):
            self.verify("def calculate_total():\n    return 1\n")

    def test_invalid_terms_file_blocks_even_valid_english_code(self):
        for payload in (
            b"{",
            b"\xff",
            b"[]",
            b"{}",
            b'{"terms": [], "skip": ["*"]}',
            b'{"terms": "kpis"}',
            b'{"terms": [1]}',
            b'{"terms": [""]}',
            b'{"terms": ["KPIs"]}',
            b'{"terms": ["kpis*"]}',
            b'{"terms": ["kpis", "kpis"]}',
        ):
            with self.subTest(payload=payload):
                self.terms_file.write_bytes(payload)
                with self.assertRaises(policy.LanguageCheckError):
                    self.verify("def calculate_total():\n    return 1\n")

    def test_bundled_vocabulary_contains_dashboard_acronym(self):
        bundled = json.loads((ROOT / "hooks/scripts/technical_terms.json").read_text(encoding="utf-8"))
        self.assertIn("kpis", bundled["terms"])


if __name__ == "__main__":
    unittest.main()
