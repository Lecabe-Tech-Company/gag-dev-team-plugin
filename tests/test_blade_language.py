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
            '<script>const quantidade = 1;</script>',
            '<div x-data="{ quantidade: 1 }"></div>',
            '<button onclick="quantidade()">Text</button>',
            '<div x-show="quantidade"></div>',
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


if __name__ == "__main__":
    unittest.main()
