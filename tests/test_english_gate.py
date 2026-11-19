"""Exercise committed PR diffs; external Git traffic and Graphify alone are fake."""
import contextlib
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_graphify_hook as graph_tests


class EnglishGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="english gate qa ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q", "-b", "prod")
        self.git("config", "user.name", "QA")
        self.git("config", "user.email", "qa@example.invalid")
        self.write(".gitignore", "graphify-out/\n")
        self.write("old.py", "def calculate_total():\n    return 1\n")
        self.write("legacy.py", "def calcular_total():\n    return 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("remote", "add", "origin", "https://github.com/owner/repo.git")
        for branch in ("prod", "stage"):
            self.git("update-ref", "refs/remotes/origin/" + branch, self.base)
        self.git("checkout", "-qb", "codex/feature/english-code")
        self.hook = graph_tests.hook
        self.original_run = self.hook.run
        self.graphify_calls = 0
        self.graphify_binary = shutil.which("graphify") or "fake-graphify"
        self.request = {"cwd": str(self.root), "base": "prod", "head": None,
                        "repo": "owner/repo"}

    def git(self, *arguments):
        return subprocess.check_output(["git", *arguments], cwd=self.root,
                                       stderr=subprocess.DEVNULL).decode()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")

    def commit(self, files):
        for relative, content in files.items():
            self.write(relative, content)
        self.git("add", ".")
        self.git("commit", "-qm", "feature")

    def fake_run(self, arguments, **options):
        if arguments[:2] == ["git", "fetch"]:
            return b""
        if arguments[:2] == ["git", "ls-remote"]:
            return (self.git("rev-parse", "HEAD").strip()
                    + "\trefs/heads/codex/feature/english-code\n").encode()
        if arguments[0] == self.graphify_binary:
            self.graphify_calls += 1
            output = Path(arguments[arguments.index("--out") + 1]) / "graphify-out"
            output.mkdir(parents=True)
            (output / "graph.json").write_text('{"nodes":[],"edges":[]}', encoding="utf-8")
            return b""
        return self.original_run(arguments, **options)

    def analyze(self):
        with patch.object(self.hook, "run", side_effect=self.fake_run):
            return self.hook.analyze_pr(self.request, self.graphify_binary)

    def test_unaccented_and_mixed_identifiers_block_with_source_location(self):
        cases = (
            ("orders.py", "def calculate_total(pedido):\n    return pedido\n"),
            ("order_service.php", "<?php class OrderService { public function calcularTotal($quantidade) { return $quantidade; } }\n"),
            ("orders.js", "const orderQuantidade = 2;\n"),
            ("orders.js", "const {pedido} = order;\n"),
            ("orders.js", "const order = {pedido};\n"),
        )
        for relative, content in cases:
            with self.subTest(path=relative):
                self.commit({relative: content})
                with self.assertRaises(self.hook.GateError) as denied:
                    self.analyze()
                self.assertIn(relative, str(denied.exception))
                self.assertRegex(str(denied.exception), r":\d+")
                self.git("rm", relative)
                self.git("commit", "-qm", "remove invalid fixture")

    def test_portuguese_file_and_directory_names_block(self):
        for relative in ("calcular_total.py", "pedidos/total.py"):
            with self.subTest(path=relative):
                self.commit({relative: "def calculate_total():\n    return 1\n"})
                with self.assertRaises(self.hook.GateError) as denied:
                    self.analyze()
                self.assertIn(relative, str(denied.exception))
                self.git("rm", relative)
                self.git("commit", "-qm", "remove invalid path")

    def test_rename_only_to_portuguese_name_is_blocked(self):
        self.git("mv", "old.py", "pedido.py")
        self.git("commit", "-qm", "rename")
        with self.assertRaises(self.hook.GateError) as denied:
            self.analyze()
        self.assertIn("pedido.py", str(denied.exception))

    def test_frontend_text_and_portuguese_documentation_are_allowed(self):
        self.commit({
            "order_form.php": "<?php $field = TextInput::make('name')->label('Nome do cliente');\n"
                              "$labels = [0 => 'Nome'];\n",
            "orders.py": '"""Planejamento e acompanhamento podem ser em português."""\n'
                         "# Este comentário documenta a operação.\n"
                         "def calculate_total(order_count):\n    return order_count\n",
            "planejamento.md": "# Planejamento\nCriar formulário e acompanhar a entrega.\n",
        })
        self.analyze()
        record = json.loads((self.root / "graphify-out/pr-check/prod/check.json").read_text())
        self.assertIn("planejamento.md", record["skipped"])
        self.assertEqual(self.graphify_calls, 1)

    def test_unchanged_legacy_identifier_does_not_force_bulk_translation(self):
        self.commit({"legacy.py": "def calcular_total():\n    return 1\n\n"
                                  "def calculate_total():\n    return 2\n"})
        self.analyze()

    def test_technical_string_keys_are_not_frontend_labels(self):
        self.commit({"orders.js": "const order = {pedido: 1};\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_quoted_technical_string_keys_are_not_frontend_labels(self):
        self.commit({"orders.js": "const order = {'pedido': 1};\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_frontend_field_identifiers_are_distinct_from_visible_labels(self):
        self.commit({"order_form.php": "<?php $field = TextInput::make('quantidade')->label('Quantidade');\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()
        self.commit({"order_form.php": "<?php $field = TextInput::make('quantity')->label('Quantidade');\n"})
        self.analyze()

    def test_schema_identifiers_are_not_frontend_text(self):
        self.commit({"order_schema.php": "<?php Schema::create('pedidos', function ($table) { $table->id(); });\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_internal_key_access_is_not_frontend_text(self):
        self.commit({"orders.py": "def calculate_total(order):\n    return order['quantidade']\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_uppercase_constants_and_accented_identifiers_are_checked(self):
        for content in ("PEDIDO_TOTAL = 1\n", "quantidade = 2\n", "cálculo = 3\n"):
            with self.subTest(content=content):
                self.commit({"orders.py": content})
                with self.assertRaises(self.hook.GateError):
                    self.analyze()

    def test_string_statement_does_not_hide_later_code_on_same_line(self):
        self.commit({"orders.py": "'display'; pedido = 1\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_interpolation_expressions_are_code_even_inside_frontend_text(self):
        cases = {
            "orders.py": 'label = f"Pedido {pedido}"\n',
            "orders.js": 'const label = `Pedido ${pedido}`;\n',
            "order_form.php": '<?php $field = TextInput::make("quantity")->label("Pedido {$pedido}");\n',
        }
        for relative, content in cases.items():
            with self.subTest(path=relative):
                self.commit({relative: content})
                with self.assertRaises(self.hook.GateError):
                    self.analyze()
                self.git("rm", relative)
                self.git("commit", "-qm", "remove invalid interpolation fixture")

    def test_malformed_changed_code_does_not_claim_complete_analysis(self):
        cases = {
            "orders.py": "def calculate_total(:\n    return 1\n",
            "orders.js": "const calculateTotal = ;\n",
            "order_service.php": "<?php function calculateTotal( { return 1; }\n",
        }
        for relative, content in cases.items():
            with self.subTest(path=relative):
                self.commit({relative: content})
                with self.assertRaises(self.hook.GateError):
                    self.analyze()
                self.git("rm", relative)
                self.git("commit", "-qm", "remove malformed fixture")

    def test_portuguese_name_is_not_accepted_as_a_rare_english_word(self):
        self.commit({"orders.py": 'nome = "Order"\n'})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_compact_nested_configuration_keys_are_checked(self):
        cases = {
            "settings.json": '{"order": {"pedido": 1}}\n',
            "settings.toml": 'order = { pedido = 1 }\n',
            "order_settings.toml": '[pedido]\ncount = 1\n',
        }
        for relative, content in cases.items():
            with self.subTest(path=relative):
                self.commit({relative: content})
                with self.assertRaises(self.hook.GateError):
                    self.analyze()
                self.git("rm", relative)
                self.git("commit", "-qm", "remove invalid configuration fixture")

    def test_python_binding_fields_are_identifiers_even_without_name_nodes(self):
        cases = (
            "try:\n    pass\nexcept Exception as pedido:\n    pass\n",
            "def calculate_total():\n    global pedido\n    return 1\n",
            "match 1:\n    case pedido:\n        pass\n",
            "from pedidos import Order\n",
        )
        for content in cases:
            with self.subTest(content=content):
                self.commit({"orders.py": content})
                with self.assertRaises(self.hook.GateError):
                    self.analyze()

    def test_supported_typed_frontend_code_keeps_visible_portuguese_text(self):
        self.commit({
            "order_types.ts": "interface Order { count: number }\nconst order: Order = {count: 1};\n",
            "order_label.tsx": "const OrderLabel = () => <span>Pedido aprovado</span>;\n",
            "order_view.jsx": "const OrderView = () => <div>Quantidade disponível</div>;\n",
        })
        self.analyze()
        self.assertEqual(self.graphify_calls, 1)

    def test_missing_dictionary_blocks_instead_of_disabling_the_gate(self):
        self.commit({"orders.py": "order_count = 1\n"})
        sys.path.insert(0, str(graph_tests.ROOT / "hooks/scripts"))
        import english_code
        with patch.object(english_code, "DICTIONARY", self.root / "missing_dictionary.dic"):
            with self.assertRaises(self.hook.GateError) as denied:
                self.analyze()
        self.assertIn("dictionary", str(denied.exception))
        self.assertEqual(self.graphify_calls, 0)

    def test_master_target_exception_is_limited_to_the_official_plugin(self):
        self.commit({"orders.py": "order_count = 1\n"})
        self.git("update-ref", "refs/remotes/origin/master", self.base)
        self.request["base"] = "master"
        with self.assertRaises(self.hook.GateError):
            self.analyze()
        self.git("remote", "set-url", "origin", "https://github.com/Lecabe-Tech-Company/gag-dev-team-plugin.git")
        self.request["repo"] = "Lecabe-Tech-Company/gag-dev-team-plugin"
        self.analyze()
        record = json.loads((self.root / "graphify-out/pr-check/master/check.json").read_text())
        self.assertEqual(record["base"], "master")

    def test_prose_and_fixture_strings_do_not_become_technical_keys(self):
        self.commit({
            "orders.py": 'source = r"""\n\'pedido\': 1\n"""\n',
            "orders.js": "const source = `\n'pedido': 1\n`;\n",
            "settings.toml": 'notes = """\n"pedido": 1\n"""\n'
                             'model_reasoning_effort = "low"\norderCount = 1\n'
                             'message = "{ pedido = 1 }"\n',
        })
        self.analyze()

    def test_toml_quoted_and_dotted_keys_are_checked(self):
        for content in ('"pedido" = 1\n', 'order."pedido" = 1\n', '["pedido"]\ncount = 1\n',
                        '[order]\n[order.details]\nnote = """Doc"""\npedido = 1\n'):
            with self.subTest(content=content):
                self.commit({"settings.toml": content})
                with self.assertRaises(self.hook.GateError) as denied:
                    self.analyze()
                self.assertIn("pedido", str(denied.exception))

    def test_added_configuration_key_is_checked_when_first_line_is_unchanged(self):
        self.commit({"settings.json": '{\n  "order": {\n    "count": 1\n  }\n}\n'})
        self.git("update-ref", "refs/remotes/origin/prod", self.git("rev-parse", "HEAD").strip())
        self.commit({"settings.json": '{\n  "order": {\n    "count": 1,\n    "pedido": 2\n  }\n}\n'})
        with self.assertRaises(self.hook.GateError) as denied:
            self.analyze()
        self.assertIn("pedido", str(denied.exception))
        self.assertIn("settings.json:4:", str(denied.exception))

    def test_old_key_at_one_path_does_not_exempt_new_key_at_another_path(self):
        self.commit({"settings.json": '{"legacy": {"pedido": 1}}\n'})
        self.git("update-ref", "refs/remotes/origin/prod", self.git("rev-parse", "HEAD").strip())
        self.commit({"settings.json": '{"legacy": {"pedido": 1}, "order": {"pedido": 2}}\n'})
        with self.assertRaises(self.hook.GateError) as denied:
            self.analyze()
        self.assertIn("pedido", str(denied.exception))

    def test_python_mapping_rest_is_a_binding_identifier(self):
        self.commit({"orders.py": "match {}:\n    case {'count': count, **pedido}:\n        pass\n"})
        with self.assertRaises(self.hook.GateError) as denied:
            self.analyze()
        self.assertIn("pedido", str(denied.exception))

    def test_portuguese_homographs_cannot_pass_through_suffix_expansion(self):
        for identifier in ("nomes", "dados", "valores", "clientes"):
            with self.subTest(identifier=identifier):
                self.commit({"orders.py": identifier + ' = ["Order"]\n'})
                with self.assertRaises(self.hook.GateError) as denied:
                    self.analyze()
                self.assertIn(identifier, str(denied.exception))

    def test_php_quoted_array_keys_are_internal_identifiers(self):
        self.commit({"orders.php": "<?php $order = ['pedido' => 1];\n"})
        with self.assertRaises(self.hook.GateError) as denied:
            self.analyze()
        self.assertIn("pedido", str(denied.exception))

    def test_sensitive_directories_cannot_waive_changed_code(self):
        for relative in ("secrets/orders.py", ".env.check.py"):
            with self.subTest(path=relative):
                self.commit({relative: "pedido = 1\n"})
                with self.assertRaises(self.hook.GateError):
                    self.analyze()
                self.assertEqual(self.graphify_calls, 0)
                self.git("rm", relative)
                self.git("commit", "-qm", "remove sensitive source fixture")

    def test_unlisted_unsupported_languages_do_not_skip_checks(self):
        self.commit({"orders.dart": "int calculateTotal() => 1;\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_extensionless_executable_sources_do_not_skip_checks(self):
        for mode in (0o644, 0o755):
            with self.subTest(mode=oct(mode)):
                self.write("bin/orders", "#!/usr/bin/env python3\npedido = 1\n")
                (self.root / "bin/orders").chmod(mode)
                self.git("add", ".")
                self.git("commit", "-qm", "extensionless source")
                with self.assertRaises(self.hook.GateError):
                    self.analyze()

    def test_unsupported_code_is_not_silently_marked_compliant(self):
        self.commit({"orders.ex": "defmodule Orders do\n  def calculate_total(), do: 1\nend\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_binary_disguised_as_code_cannot_skip_language_verification(self):
        self.commit({"orders.py": b"def pedido():\x00\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_unknown_identifier_requires_resolution(self):
        self.commit({"orders.py": "def xyzzq_order():\n    return 1\n"})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_documentation_only_pr_does_not_require_english_prose(self):
        self.commit({"planejamento.md": "# Especificação\nO acompanhamento pode ser em português.\n"})
        self.analyze()
        self.assertEqual(self.graphify_calls, 0)

    def test_css_native_contracts_and_frontend_text_are_allowed(self):
        self.commit({"dashboard/styles.css": ".order-card { --row-gap: 8px; display: grid; gap: var(--row-gap); }\n"
                                            ".order-card::before { content: 'Pedidos'; }\n"
                                            "@media (min-width: 40rem) { .order-card { display: block; } }\n"})
        self.analyze()

    def test_css_custom_identifiers_and_new_file_names_remain_english(self):
        cases = (
            ("dashboard/styles.css", ".pedido-card { display: grid; }\n"),
            ("dashboard/styles.css", ":root { --quantidade: 1; }\n"),
            ("dashboard/styles.css", "@keyframes pedido-pulse { from { opacity: 0; } to { opacity: 1; } }\n"),
            ("dashboard/pedidos.css", ".order-card { display: grid; }\n"),
        )
        for relative, content in cases:
            with self.subTest(path=relative, content=content):
                self.commit({relative: content})
                with self.assertRaises(self.hook.GateError):
                    self.analyze()
                self.git("rm", relative)
                self.git("commit", "-qm", "remove invalid CSS fixture")

    def lockfile(self):
        dependencies = {"next": "16.4.6", "lightningcss": "1.30.1"}
        integrity = "sha512-" + base64.b64encode(hashlib.sha512(b"synthetic package").digest()).decode("ascii")
        manifest = {"name": "gag-dashboard", "version": "0.1.0", "private": True,
                    "dependencies": dependencies}
        lock = {"name": "gag-dashboard", "version": "0.1.0", "lockfileVersion": 3, "requires": True,
                "packages": {"": {"name": "gag-dashboard", "version": "0.1.0", "dependencies": dependencies}}}
        for name, version in dependencies.items():
            lock["packages"]["node_modules/" + name] = {
                "version": version, "resolved": "https://registry.npmjs.org/" + name + "/-/" + name + "-" + version + ".tgz",
                "integrity": integrity,
            }
        return manifest, lock

    def test_npm_lockfile_external_dependency_contracts_are_not_local_identifiers(self):
        manifest, lock = self.lockfile()
        self.commit({"dashboard/package.json": json.dumps(manifest),
                     "dashboard/package-lock.json": json.dumps(lock)})
        self.analyze()

    def test_lockfile_name_does_not_exempt_unexpected_portuguese_local_keys(self):
        manifest, lock = self.lockfile()
        untranslated_key = "quantidade"
        lock[untranslated_key] = 1
        self.commit({"dashboard/package.json": json.dumps(manifest),
                     "dashboard/package-lock.json": json.dumps(lock)})
        with self.assertRaises(self.hook.GateError):
            self.analyze()

    def test_bash_native_commands_and_english_variables_are_allowed(self):
        self.commit({"scripts/check_runtime.sh": "#!/usr/bin/env bash\nset -euo pipefail\n"
                                               "check_runtime() { local runtime_path='node'; printf '%s\\n' \"$runtime_path\"; }\n"
                                               "check_runtime\n"})
        self.analyze()

    def test_bash_portuguese_variables_functions_and_malformed_syntax_are_blocked(self):
        cases = ("#!/usr/bin/env bash\nquantidade=1\nprintf '%s\\n' \"$quantidade\"\n",
                 "#!/usr/bin/env bash\ncalcular_total() { printf 'ready'; }\n",
                 "#!/usr/bin/env bash\nif true; then\nprintf 'ready'\n")
        for content in cases:
            with self.subTest(content=content):
                self.commit({"scripts/check_runtime.sh": content})
                with self.assertRaises(self.hook.GateError):
                    self.analyze()

    def test_workflow_yaml_and_english_run_identifiers_are_allowed(self):
        with self.subTest(style="inline"):
            self.commit({".github/workflows/inline.yml": "jobs:\n  build:\n    steps:\n      - run: runtime_path=node\n"})
            self.analyze()
        self.commit({".github/workflows/build.yml": "name: Build\non: push\njobs:\n  build:\n"
                                                   "    runs-on: ubuntu-latest\n    steps:\n      - run: |\n"
                                                   "          runtime_path='node'\n          printf '%s\\n' \"$runtime_path\"\n"})
        self.analyze()

    def test_yaml_portuguese_keys_run_variables_and_invalid_graphs_are_blocked(self):
        cases = ("quantidade: 1\n",
                 "jobs:\n  build:\n    steps:\n      - run: quantidade=1\n",
                 "jobs:\n  build:\n    steps:\n      - run: >\n          runtime_path=node\n",
                 "jobs:\n  build:\n    steps:\n      - run: |\n          quantidade=1\n          printf '%s' \"$quantidade\"\n",
                 "jobs: [\n",
                 "settings: &settings\n  child: *settings\n")
        for content in cases:
            with self.subTest(content=content):
                self.commit({"dashboard/settings.yaml": content})
                with self.assertRaises(self.hook.GateError):
                    self.analyze()


class ExportLanguageContextTests(unittest.TestCase):
    SHEET_HELPER = """<?php
function exportRows($workbook, string $sheet): array {
    $rows = $workbook->getSheetByName($sheet)->toArray();
    $headers = array_shift($rows);
    return array_map(fn (array $row): array => array_combine($headers, $row), $rows);
}
"""

    @classmethod
    def setUpClass(cls):
        source = graph_tests.ROOT / "hooks/scripts/english_code.py"
        spec = importlib.util.spec_from_file_location("qa_export_language", source)
        cls.language = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.language)

    def check_source(self, source, path="tests/export_test.php"):
        return self.language.validate_changes([{
            "path": path,
            "content": source,
            "added_lines": set(range(1, len(source.splitlines()) + 1)),
            "path_changed": True,
        }])

    def assert_accepted(self, source, path="tests/export_test.php"):
        diagnostics = self.check_source(source, path)
        self.assertEqual(diagnostics, [], "\n".join(diagnostics))

    def assert_rejected(self, source, token="nome"):
        diagnostics = self.check_source(source)
        self.assertTrue(diagnostics)
        self.assertIn(token, "\n".join(diagnostics).casefold())

    def test_standard_php_and_filament_contracts_are_accepted(self):
        self.assert_accepted("""<?php
use Filament\\Actions\\Exports\\Enums\\ExportFormat;
use PDOException;
use Throwable;
class CsvDownloader {
    public function download($stream): bool {
        if (isset($stream)) {
            fpassthru($stream);
            fclose($stream);
        }
        return auth()->check();
    }
    public function formats(): array {
        return [ExportFormat::Csv, ExportFormat::Xlsx];
    }
}
""", path="exports/csv_downloader.php")

    def test_sheet_output_headers_are_presentation_in_row_assertions(self):
        self.assert_accepted(self.SHEET_HELPER + """
$fields = exportRows($workbook, 'Campos');
expect($fields[0])->toMatchArray(['Nome' => 'RAM', 'Descrição' => 'Detalhe']);
expect($fields[0]['Descrição'])->toBe('Detalhe');
$row = exportRows($workbook, 'Opções')[0];
expect($row['Nome'])->toBe('RAM');
""")

    def test_an_unsupported_collection_wrapper_remains_blocked(self):
        self.assert_rejected(self.SHEET_HELPER + """
$row = collect(exportRows($workbook, 'Opções'))->firstWhere('ID', $id);
expect($row['Nome'])->toBe('RAM');
""")

    def test_workbook_sheet_names_are_presentation_when_used_to_inspect_sheets(self):
        self.assert_accepted("""<?php
foreach (['Campos' => ['Nome', 'RAM'], 'Opções' => ['Rótulo', 'Value']] as $sheet => [$header, $literal]) {
    $worksheet = $workbook->getSheetByName($sheet);
    $column = array_search($header, $worksheet->toArray()[0], true);
    expect($worksheet->getCell([$column + 1, 2])->getValue())->toBe($literal);
}
""")

    def test_framework_export_column_labels_can_be_combined_with_exported_values(self):
        self.assert_accepted("""<?php
use Filament\\Actions\\Exports\\Exporter;
use Filament\\Actions\\Exports\\ExportColumn;
use Filament\\Actions\\Exports\\Models\\Export;
class FieldExporter extends Exporter {
    public static function getColumns(): array {
        return [ExportColumn::make('name')->label('Nome')];
    }
}
$columns = collect(FieldExporter::getColumns())
    ->mapWithKeys(fn ($column): array => [$column->getName() => $column->getLabel()])->all();
$exporter = new FieldExporter(new Export(), $columns, []);
$row = array_combine(array_values($columns), $exporter($field));
expect($row['Nome'])->toBe('RAM');
""")

    def test_python_builtins_and_php_iterable_contracts_are_accepted(self):
        self.assert_accepted("""class Registry:
    @classmethod
    def namespaces(cls):
        entries = {}
        entries.setdefault("items", [])
        return entries
""", path="hooks/registry.py")
        self.assert_accepted("""<?php
function namespaces(iterable $items): iterable { return $items; }
""")

    def test_helper_requires_reachable_same_scope_output_origin(self):
        for helper in (
            """function exportRows($book, $values, $headers): array {
    return array_map(fn ($row) => array_combine($headers, $row), $values);
    $values = $book->getSheetByName('Campos')->toArray();
    $headers = array_shift($values);
}""",
            """function exportRows($book, $payload): array {
    $unused = function () use ($book) {
        $values = $book->getSheetByName('Campos')->toArray();
        $headers = array_shift($values);
        return array_map(fn ($row) => array_combine($headers, $row), $values);
    };
    return $payload;
}""",
        ):
            with self.subTest(helper=helper):
                self.assert_rejected("<?php\n" + helper + "\n$output = exportRows($book, $payload, $headers); expect($output['Nome'])->toBe('RAM');")

    def test_output_sources_require_preceding_unmodified_contracts(self):
        columns = """$columns = collect(FieldExporter::getColumns())->mapWithKeys(fn ($column): array => [$column->getName() => $column->getLabel()])->all();
$exporter = new FieldExporter(new Export(), $columns, []);
"""
        mapping = "$row = array_combine(array_values($columns), $exporter($field));\n"
        cases = (
            mapping + "expect($row['Nome'])->toBe('RAM');\n" + columns,
            columns + "$columns = $payload;\n" + mapping + "expect($row['Nome'])->toBe('RAM');",
            columns + "$exporter = $callback;\n" + mapping + "expect($row['Nome'])->toBe('RAM');",
            "$rows = iterator_to_array($reader->getRecords(), false);\nexpect($rows[0]['Nome'])->toBe('RAM');\n$reader->setHeaderOffset(0);",
            "$reader->setHeaderOffset(0);\n$reader = $payload;\n$rows = iterator_to_array($reader->getRecords(), false);\nexpect($rows[0]['Nome'])->toBe('RAM');",
        )
        self.assert_rejected(self.SHEET_HELPER + "\n$fields = $payload; expect($fields['Nome'])->toBe('RAM'); $fields = exportRows($book, 'Campos');")
        for source in cases:
            with self.subTest(source=source):
                self.assert_rejected("<?php\n" + source)

    def test_presentation_context_does_not_exempt_portuguese_code_identifiers(self):
        for fragment, token in (
            ("$nome = 1;", "nome"),
            ("function calcularTotal($count) { return $count; }", "calcular"),
            ("$csvQuantidade = 1;", "quantidade"),
        ):
            with self.subTest(fragment=fragment):
                self.assert_rejected(self.SHEET_HELPER + """
$fields = exportRows($workbook, 'Campos');
expect($fields[0]['Nome'])->toBe('RAM');
""" + fragment, token)

    def test_technical_keys_remain_checked_beside_identical_display_labels(self):
        for fragment in (
            "$payload = ['Nome' => 1];",
            "$value = $payload['nome'];",
            "$field = TextInput::make('nome')->label('Nome');",
            "expect($payload)->toMatchArray(['Nome' => 'RAM']);",
            "$value = $payload[$fields[0]['ID']]['nome'];",
            "expect($payload[$fields[0]['ID']])->toMatchArray(['Nome' => 'RAM']);",
        ):
            with self.subTest(fragment=fragment):
                self.assert_rejected(self.SHEET_HELPER + """
$field = TextInput::make('name')->label('Nome');
$fields = exportRows($workbook, 'Campos');
""" + fragment)

    def test_generic_array_combine_helpers_do_not_make_technical_payload_keys_presentation(self):
        self.assert_rejected("""<?php
function mapRows($rows): array {
    $headers = array_shift($rows);
    return array_map(fn (array $row): array => array_combine($headers, $row), $rows);
}
$fields = mapRows($payload);
expect($fields[0]['Nome'])->toBe('RAM');
""")

    def test_an_arbitrary_callable_named_exporter_cannot_exempt_technical_keys(self):
        for setup in (
            "$exporter = fn ($field): array => [$field];",
            "class FakeExporter { public function __invoke($field): array { return [$field]; } }\n"
            "$exporter = new FakeExporter();",
        ):
            with self.subTest(setup=setup):
                self.assert_rejected("<?php\n" + setup + """
$headers = ['Nome'];
$row = array_combine($headers, $exporter($field));
expect($row['Nome'])->toBe('RAM');
""")

    def test_reassignment_revokes_presentation_map_provenance(self):
        self.assert_rejected(self.SHEET_HELPER + """
$fields = exportRows($workbook, 'Campos');
$fields = $payload;
expect($fields['Nome'])->toBe('RAM');
""")

    def test_presentation_map_provenance_does_not_leak_between_function_scopes(self):
        self.assert_rejected(self.SHEET_HELPER + """
function inspectOutput($workbook): array {
    $row = exportRows($workbook, 'Campos')[0];
    return [$row['Nome']];
}
function processData($payload): array {
    $row = $payload;
    return [$row['Nome']];
}
""")

    def test_helper_provenance_does_not_cross_namespaces(self):
        sources = (
            ("bracketed", """<?php
namespace Alpha {
    function rows($workbook, string $sheet): array {
        $values = $workbook->getSheetByName($sheet)->toArray();
        $headers = array_shift($values);
        return array_map(fn (array $row): array => array_combine($headers, $row), $values);
    }
}
namespace Beta {
    LOCAL_HELPER
    $output = rows($payload);
    expect($output['Nome'])->toBe('RAM');
}
"""),
            ("unbracketed", """<?php
namespace Alpha;
function rows($workbook, string $sheet): array {
    $values = $workbook->getSheetByName($sheet)->toArray();
    $headers = array_shift($values);
    return array_map(fn (array $row): array => array_combine($headers, $row), $values);
}
namespace Beta;
LOCAL_HELPER
$output = rows($payload);
expect($output['Nome'])->toBe('RAM');
"""),
        )
        for style, source in sources:
            for local_helper in ("function rows($payload): array { return $payload; }", ""):
                with self.subTest(style=style, local_helper=bool(local_helper)):
                    self.assert_rejected(source.replace("LOCAL_HELPER", local_helper))

    def test_a_presentation_map_does_not_hide_a_parser_failure(self):
        with self.assertRaises(self.language.LanguageCheckError):
            self.check_source(self.SHEET_HELPER + "\nfunction calculateTotal( { return 1; }\n")


class NativeLanguageGateTests(unittest.TestCase):
    setUp = EnglishGateTests.setUp
    git = EnglishGateTests.git
    write = EnglishGateTests.write
    commit = EnglishGateTests.commit
    fake_run = EnglishGateTests.fake_run

    def invoke(self, harness, event):
        path = graph_tests.ROOT / "hooks/scripts/team_hooks.py"
        spec = importlib.util.spec_from_file_location("qa_english_team_hooks", path)
        team = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(team)
        output = io.StringIO()
        input_stream = io.TextIOWrapper(io.BytesIO(json.dumps(event).encode("utf-8")), encoding="utf-8")
        with input_stream, patch.object(sys, "argv", [str(path), harness, "PreToolUse"]), \
                patch.object(sys, "stdin", input_stream), \
                patch.object(team.graphify_hook, "run", side_effect=self.fake_run), \
                patch.object(team.graphify_hook, "ensure_graphify", return_value=self.graphify_binary), \
                contextlib.redirect_stdout(output):
            team.main()
        return json.loads(output.getvalue())

    def test_every_native_harness_blocks_before_pr_creation(self):
        self.commit({"orders.py": "def calculate_total(pedido):\n    return pedido\n"})
        command = "gh pr create --base prod --title 'Código' --body 'Acompanhamento em português'"
        for harness in ("codex", "claude", "cursor", "antigravity"):
            if harness == "antigravity":
                event = {"toolCall": {"name": "run_command", "args": {
                    "CommandLine": command, "Cwd": str(self.root)}}}
            else:
                event = {"tool_name": "Bash", "tool_input": {"command": command},
                         "cwd": str(self.root)}
            with self.subTest(harness=harness):
                result = self.invoke(harness, event)
                if harness == "cursor":
                    self.assertEqual(result.get("permission"), "deny")
                elif harness == "antigravity":
                    self.assertEqual(result.get("decision"), "deny")
                else:
                    self.assertEqual(result.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
                self.assertIn("orders.py", json.dumps(result))

    def test_mcp_creation_passes_through_the_same_language_gate(self):
        self.commit({"orders.py": "def pedido():\n    return 1\n"})
        event = {"tool_name": "mcp__github__create_pull_request", "cwd": str(self.root),
                 "tool_input": {"owner": "owner", "repo": "repo", "head": "codex/feature/english-code", "base": "prod"}}
        result = self.invoke("codex", event)
        self.assertEqual(result.get("hookSpecificOutput", {}).get("permissionDecision"), "deny")
        self.assertIn("orders.py", json.dumps(result))
