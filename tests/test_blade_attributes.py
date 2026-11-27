"""Executable HTML and Alpine attributes receive the same language checks as scripts."""
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("attribute_policy", ROOT / "hooks/scripts/english_code.py")
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class BladeAttributeTests(unittest.TestCase):
    def verify(self, source, lines=None):
        return policy.validate_changes([{
            "path": "resources/views/header.blade.php",
            "content": source,
            "added_lines": set(lines or range(1, source.count("\n") + 2)),
            "path_changed": False,
        }])

    def test_supported_alpine_and_event_attributes_allow_english_code(self):
        for attribute in (
            'x-data="{ open: false, orderCount: 0 }"',
            'x-show="open &amp;&amp; orderCount &gt; 0"',
            'x-on:click="open = !open"',
            'x-on:click="open = true; orderCount += 1"',
            '@click="open = !open"',
            'x-bind:class="{ active: open }"',
            ':class="{ active: open }"',
            'onclick="window.console.log(event)"',
            'onclick="window.console.log(event); return false"',
        ):
            with self.subTest(attribute=attribute):
                self.assertEqual(self.verify(f'<button {attribute}>Relatório</button>\n'), [])

    def test_each_executable_attribute_reports_identifier_on_original_line(self):
        for attribute in (
            'x-data="{ quantidade: 1 }"',
            'x-show="quantidade &gt; 0"',
            'x-on:click="quantidade += 1"',
            '@click="quantidade += 1"',
            'x-bind:class="{ active: quantidade }"',
            ':class="{ active: quantidade }"',
            'onclick="quantidade()"',
        ):
            with self.subTest(attribute=attribute):
                diagnostics = self.verify(f'<p>Resumo</p>\n<button {attribute}>Abrir</button>\n')
                self.assertTrue(any("header.blade.php:2:" in item and "'quantidade'" in item
                                    for item in diagnostics), diagnostics)

    def test_multiline_attributes_preserve_changed_line_boundary(self):
        source = '''<div x-data="{
    quantidade: 1,
    orderCount: 2
}">Resumo</div>
'''
        self.assertEqual(self.verify(source, {3}), [])
        diagnostics = self.verify(source, {2})
        self.assertTrue(any("header.blade.php:2:" in item and "'quantidade'" in item
                            for item in diagnostics), diagnostics)

    def test_handler_on_the_only_changed_line_cannot_escape_verification(self):
        source = '<p>Resumo</p>\n<button @click="quantidade()">Abrir</button>\n'
        diagnostics = self.verify(source, {2})
        self.assertTrue(any("header.blade.php:2:" in item and "'quantidade'" in item
                            for item in diagnostics), diagnostics)

    def test_encoded_line_breaks_do_not_move_identifiers_outside_changed_lines(self):
        source = '<div x-show="&#10;quantidade &gt; 0">Resumo</div>\n'
        diagnostics = self.verify(source, {1})
        self.assertTrue(any("header.blade.php:1:" in item and "'quantidade'" in item
                            for item in diagnostics), diagnostics)

    def test_attribute_frontend_strings_and_comments_are_not_identifiers(self):
        source = '''<button x-on:click="/* quantidade */ window.console.log('Produção da equipe')">
Resumo
</button>
'''
        self.assertEqual(self.verify(source), [])

    def test_static_attribute_content_is_not_executable(self):
        source = '''<div title='Exemplo x-show="quantidade"'>Resumo</div>
'''
        self.assertEqual(self.verify(source), [])

    def test_blade_comments_do_not_make_example_attributes_executable(self):
        source = '{{-- <div x-show="quantidade">Exemplo</div> --}}\n<p>Resumo</p>\n'
        self.assertEqual(self.verify(source), [])

    def test_blade_component_bindings_keep_php_expression_semantics(self):
        self.assertEqual(self.verify('<x-alert :title="$order->getLabel()" />\n'), [])
        diagnostics = self.verify('<x-alert :title="$pedido->getLabel()" />\n')
        self.assertTrue(any("'pedido'" in item for item in diagnostics), diagnostics)

    def test_wire_init_method_names_are_checked_on_original_lines(self):
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                source = f'<p>Resumo</p>\n<div wire:init={quote}loadOrders{quote}></div>'
                self.assertEqual(self.verify(source), [])
                result = self.verify(source.replace('loadOrders', 'carregarPedidos'), {2})
                for token in ("carregar", "pedidos"):
                    self.assertTrue(any("header.blade.php:2:" in item and f"'{token}'" in item for item in result), result)

    def test_wire_init_uncovered_expressions_fail_closed(self):
        for source in (
            '<div wire:init=""></div>',
            '<div wire:init="loadOrders()"></div>',
            '<div wire:init="loadOrders(1)"></div>',
            '<div wire:init="loadOrders; otherAction"></div>',
            '<div wire:init="order.loadOrders"></div>',
            '<div wire:init=loadOrders></div>',
            '<div wire:init.lazy="loadOrders"></div>',
            '<div wire:click="loadOrders"></div>',
        ):
            with self.subTest(source=source):
                with self.assertRaises(policy.LanguageCheckError):
                    self.verify(source)

    def test_malformed_or_uncovered_attributes_still_fail_closed(self):
        for source in (
            '<div x-data="{ open: }"></div>',
            '<div x-show="open &&"></div>',
            '<button onclick="const = ;">Abrir</button>',
            '<div x-show=open></div>',
            '<div x-data="{ open: true }></div>',
            '<style>.active { color: red; }</style>',
            '<div x-show="{{ $orderCount }}"></div>',
        ):
            with self.subTest(source=source):
                with self.assertRaises(policy.LanguageCheckError):
                    self.verify(source)


if __name__ == "__main__":
    unittest.main()
