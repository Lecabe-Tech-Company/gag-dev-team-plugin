"""Blade source coverage and original-line language diagnostics."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("english_code", ROOT / "hooks/scripts/english_code.py")
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class BladeLanguageTests(unittest.TestCase):
    def verify(self, source, lines=None):
        return policy.validate_changes([{
            "path": "resources/views/header.blade.php",
            "content": source,
            "added_lines": set(lines or range(1, source.count("\n") + 2)),
            "path_changed": False,
        }])

    def test_frontend_portuguese_and_nested_php_remain_allowed(self):
        source = """@php
    $active = $this->getActiveDashboard();
    $compactHeader = count(['header' => ['active' => true]]) > 0;
@endphp
<h2>Relatório da equipe</h2>
@if ($compactHeader && count(['header' => $active]))
    {{ $active->getLabel() }}
@else
    {!! $this->filtersForm !!}
@endif
@foreach ($available as $option)
    <a @class(['active' => $option === $active])>{{ $option->getLabel() }}</a>
@endforeach
"""
        self.assertEqual(self.verify(source), [])

    def test_identifier_in_each_executable_region_is_rejected(self):
        for region in (
            "{{ $quantidade }}",
            "@if($active){{ $quantidade }}@endif",
            "@php $active = true; @endphp{{ $quantidade }}",
            "<?php $quantidade = 1; ?>",
            "@php /* @endphp */ $quantidade = 1; @endphp",
            "{{ SectorDashboardEnum::Teste }}",
            '<x-alert :title="$quantidade" />',
            "{!! $quantidade !!}",
            "@php $quantidade = 1; @endphp",
            "@if ($quantidade > 0)Text@endif",
            "@foreach ($orders as $pedido)Text@endforeach",
            "<div @class(['active' => $quantidade > 0])>Text</div>",
        ):
            with self.subTest(region=region):
                result = self.verify("<p>Resumo</p>\n" + region + "\n")
                self.assertTrue(result)
                self.assertTrue(any(":2:" in message for message in result), result)

    def test_only_changed_original_lines_are_checked(self):
        source = "@php\n$quantidade = 1;\n$orderCount = 2;\n@endphp\n"
        self.assertEqual(self.verify(source, {3}), [])

    def test_comment_delimiters_and_strings_do_not_truncate_php(self):
        source = """{{-- {{ $quantidade }} @php invalid @endphp --}}
@php
    $message = '@endphp }} {!!';
    // @endphp }}
    $orderCount = 1;
@endphp
{{ $message }}
"""
        self.assertEqual(self.verify(source), [])

    def test_malformed_or_uncovered_code_blocks_the_analysis(self):
        for source in (
            "{{ $orderCount ",
            "@if ($active)<p>Text</p>",
            "@foreach ($orders as $order)Text@endif",
            "@endif",
            "@csrf($quantidade)",
            "@endif($quantidade)",
            "@php $orderCount = ; @endphp",
            "@php $orderCount = 1;",
            "@unknownDirective($orderCount)",
            '<div wire:click="quantidade"></div>',
            '<div wire:click=quantidade></div>',
            '<x-alert :title="$quantidade />',
        ):
            with self.subTest(source=source):
                with self.assertRaises(policy.LanguageCheckError):
                    self.verify(source)

    def test_directive_strings_and_comment_parentheses_preserve_line_mapping(self):
        source = """@if (count(['label' => ') }} @endif']) > 0)
<p>Resumo</p>
{{ $quantidade }}
@endif
"""
        result = self.verify(source, {3})
        self.assertTrue(any(":3:" in item for item in result), result)

    def test_real_sector_header_uses_original_changed_lines(self):
        source = (ROOT / "tests/fixtures/sector_header.txt").read_text()
        self.assertEqual(self.verify(source, {5, 8}), [])

    def test_empty_frontend_template_is_allowed(self):
        self.assertEqual(self.verify("<p>Olá, equipe! Relatório de produção.</p>"), [])

    def test_javascript_blocks_and_livewire_wrapper_allow_frontend_text(self):
        for opening, closing in (
            ("<script>", "</script>"),
            ('<script type="module">', "</script>"),
            ("@script\n<script>", "</script>\n@endscript"),
        ):
            with self.subTest(opening=opening):
                source = (
                    "<h2>Relatório da equipe</h2>\n"
                    + opening
                    + "\nconst message = 'Produção acumulada';\n"
                    + "const orderCount = 2;\n"
                    + "window.console.log(message, orderCount);\n"
                    + closing
                    + "\n"
                )
                self.assertEqual(self.verify(source), [])

    def test_javascript_diagnostics_reference_original_blade_lines(self):
        source = """<p>Resumo</p>
@script
<script>
const quantidade = 1;
window.console.log(quantidade);
</script>
@endscript
"""
        result = self.verify(source, {4})
        self.assertEqual(len(result), 1, result)
        self.assertIn("resources/views/header.blade.php:4:", result[0])
        self.assertIn("'quantidade'", result[0])

    def test_multiple_scripts_keep_legacy_identifiers_outside_changed_lines(self):
        source = """<script>
const quantidade = 1;
</script>
<p>Produção da equipe</p>
<script>
const orderCount = 2;
const pedido = orderCount;
</script>
"""
        self.assertEqual(self.verify(source, {6}), [])
        result = self.verify(source, {7})
        self.assertEqual(len(result), 1, result)
        self.assertIn("header.blade.php:7:", result[0])
        self.assertIn("'pedido'", result[0])

    def test_json_php_expression_and_javascript_are_both_checked(self):
        source = """@script
<script>
const chartUrl = @json(asset('js/vendor/chart.umd.min.js'));
const message = 'Produção'; const chartData = @json($orderCount);
const total = @json(
    $quantidade
);
const pedido = total;
</script>
@endscript
"""
        self.assertEqual(self.verify(source, {3}), [])
        self.assertEqual(self.verify(source, {4}), [])
        for line_number, identifier in ((6, "quantidade"), (8, "pedido")):
            with self.subTest(line_number=line_number):
                result = self.verify(source, {line_number})
                self.assertEqual(len(result), 1, result)
                self.assertIn(f"header.blade.php:{line_number}:", result[0])
                self.assertIn(f"'{identifier}'", result[0])

    def test_json_nested_expression_respects_strings_and_php_comments(self):
        source = """<script>
const chartUrl = @json(
    asset(
        // Ignore a closing parenthesis: )
        str_replace(')', '(', 'js/chart.js')
    )
);
const orderCount = 1;
</script>
"""
        self.assertEqual(self.verify(source, {8}), [])
        invalid_source = source.replace("asset(", "$quantidade(")
        result = self.verify(invalid_source, {3})
        self.assertTrue(any("header.blade.php:3:" in item for item in result), result)

    def test_javascript_comments_strings_and_unicode_preserve_locations(self):
        source = """<script>
// A produção é exibida sem meta.
const message = 'Relatório da equipe';
/* quantidade pedido */
const orderCount = 1;
const quantidade = orderCount;
</script>
"""
        self.assertEqual(self.verify(source, {2, 3, 4, 5}), [])
        result = self.verify(source, {6})
        self.assertTrue(any("header.blade.php:6:" in item for item in result), result)

    def test_assets_wrapper_preserves_php_and_script_analysis(self):
        source = """@assets
@php $orderCount = 2; @endphp
<script>
const orderCount = @json($orderCount);
window.console.log(orderCount);
</script>
@endassets
"""
        self.assertEqual(self.verify(source), [])
        for line_number, original, replacement in (
            (2, "$orderCount = 2", "$quantidade = 2"),
            (4, "const orderCount", "const quantidade"),
        ):
            with self.subTest(line_number=line_number):
                result = self.verify(source.replace(original, replacement), {line_number})
                self.assertTrue(any(f"header.blade.php:{line_number}:" in item and "'quantidade'" in item for item in result), result)

    def test_assets_wrapper_preserves_changed_line_filtering(self):
        source = "@assets\n{{ $quantidade }}\n{{ $orderCount }}\n@endassets\n"
        self.assertEqual(self.verify(source, {3}), [])
        result = self.verify(source, {2})
        self.assertTrue(any("header.blade.php:2:" in item and "'quantidade'" in item for item in result), result)

    def test_assets_wrappers_can_be_sequential_and_nested_in_control_flow(self):
        for source in (
            "@assets<p>Resumo</p>@endassets\n@assets{{ $orderCount }}@endassets",
            "@if ($active)@assets{{ $orderCount }}@endassets@endif",
            "@assets@if ($active){{ $orderCount }}@endif@endassets",
            "@assets{{-- @endassets --}}{{ '@endassets' }}@endassets",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.verify(source), [])

    def test_malformed_assets_wrappers_fail_closed(self):
        for source in (
            "@assets<p>Resumo</p>",
            "@endassets",
            "@assets($orderCount)<p>Resumo</p>@endassets",
            "@assets<p>Resumo</p>@endassets($orderCount)",
            "@assets@if ($active)<p>Resumo</p>@endassets@endif",
            "@if ($active)@assets<p>Resumo</p>@endif@endassets",
            "@assets<script>const orderCount = ;</script>@endassets",
            "@assets@unknownDirective($orderCount)@endassets",
        ):
            with self.subTest(source=source):
                with self.assertRaises(policy.LanguageCheckError):
                    self.verify(source)

    def test_livewire_directive_checks_component_arguments_and_key(self):
        source = "@livewire(\\App\\Livewire\\OrderForm::class, ['orderId' => $orderId], key('order-form-'.$orderId))"
        self.assertEqual(self.verify(source), [])
        for expression in (
            "@livewire(\\App\\Livewire\\OrderForm::class)",
            "@livewire(\\App\\Livewire\\OrderForm::class, ['orderId' => $orderId])",
        ):
            with self.subTest(expression=expression):
                self.assertEqual(self.verify(expression), [])
        for original, replacement in (
            ("OrderForm::class", "Formulario::class"),
            ("$orderId", "$quantidade"),
        ):
            with self.subTest(replacement=replacement):
                result = self.verify(source.replace(original, replacement))
                self.assertTrue(result)
                self.assertTrue(any("header.blade.php:1:" in item for item in result), result)

    def test_livewire_directive_preserves_lines_and_rejects_malformed_expressions(self):
        source = "@livewire(\n\\App\\Livewire\\OrderForm::class,\n['orderId' => $quantidade],\nkey($orderId)\n)"
        self.assertEqual(self.verify(source, {4}), [])
        result = self.verify(source, {3})
        self.assertTrue(any("header.blade.php:3:" in item and "'quantidade'" in item for item in result), result)
        for source in ("@livewire", "@livewire()", "@livewire(", "@livewire($orderId", "@livewire($orderId +)", "@livewire($orderId,,key($orderId))"):
            with self.subTest(source=source):
                with self.assertRaises(policy.LanguageCheckError):
                    self.verify(source)

    def test_assets_wrapper_does_not_allow_embedded_css(self):
        with self.assertRaises(policy.LanguageCheckError):
            self.verify("@assets\n<style>.order-count { color: red; }</style>\n@endassets")

    def test_script_syntax_and_uncovered_regions_fail_closed(self):
        for source in (
            "<script>const orderCount = ;</script>",
            "<script>const orderCount = 1;",
            "</script>",
            "@script\n<script>const orderCount = 1;</script>",
            "@endscript",
            "@script\n@script\n<script>const total = 1;</script>\n@endscript\n@endscript",
            '<script type="text/unknown">const total = 1;</script>',
            '<script src="chart.js">const total = 1;</script>',
            "<script>const total = @json($orderCount;</script>",
            "<script>const total = {{ $orderCount }};</script>",
            '<script>const total = "@json($orderCount)";</script>',
            "<script>const total = `@json($orderCount)`;</script>",
            "<script>const pattern = /@json($orderCount)/;</script>",
            "<script>// @json($orderCount)\nconst total = 1;</script>",
            "<script>@if ($active)const total = 1;@endif</script>",
            "<script><?php $orderCount = 1; ?></script>",
            "<style>.order-count { color: red; }</style>",
        ):
            with self.subTest(source=source):
                with self.assertRaises(policy.LanguageCheckError):
                    self.verify(source)


if __name__ == "__main__":
    unittest.main()
