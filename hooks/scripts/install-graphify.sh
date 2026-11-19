#!/usr/bin/env bash
# Fonte: https://github.com/Graphify-Labs/graphify#install
# stdout: somente o caminho do executável; diagnósticos vão para stderr.
set -euo pipefail
export PATH="${HOME}/.local/bin:${PATH}"
tool_root="${PLUGIN_DATA:-${XDG_DATA_HOME:-${HOME}/.local/share}/gag-dev-team-plugin}/graphify-venv"
if [[ -x "$tool_root/bin/graphify" ]]; then
    "$tool_root/bin/python" -c 'import tree_sitter_css, yaml' 2>/dev/null || "$tool_root/bin/python" -m pip install tree-sitter-css==0.25.0 PyYAML==6.0.3 >&2
    "$tool_root/bin/graphify" --version >&2
    printf '%s\n' "$tool_root/bin/graphify"
    exit 0
fi
if command -v graphify >/dev/null 2>&1; then
    graphify_path="$(command -v graphify)"
    IFS= read -r interpreter < "$graphify_path"
    interpreter="${interpreter#\#!}"
    if [[ -x "$interpreter" ]] && "$interpreter" -c 'import tree_sitter_css, yaml' 2>/dev/null; then
        graphify --version >&2
        command -v graphify
        exit 0
    fi
    # Keep an existing tool installation untouched; provision a private runtime.
    python3 -m venv "$tool_root" >&2
    "$tool_root/bin/python" -m pip install graphifyy tree-sitter-css==0.25.0 PyYAML==6.0.3 >&2
    "$tool_root/bin/graphify" --version >&2
    printf '%s\n' "$tool_root/bin/graphify"
    exit 0
fi
if command -v uv >/dev/null 2>&1; then
    uv tool install graphifyy --with tree-sitter-css==0.25.0 --with PyYAML==6.0.3 >&2
    tool_bin="$(uv tool dir --bin)"
elif command -v pipx >/dev/null 2>&1; then
    pipx install graphifyy >&2
    pipx inject graphifyy tree-sitter-css==0.25.0 PyYAML==6.0.3 >&2
    tool_bin="$(pipx environment --value PIPX_BIN_DIR)"
else
    # Ambiente isolado: não altera o Python do sistema.
    python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ obrigatório"' >&2
    tool_root="${PLUGIN_DATA:-${XDG_DATA_HOME:-${HOME}/.local/share}/gag-dev-team-plugin}/graphify-venv"
    python3 -m venv "$tool_root" >&2
    "$tool_root/bin/python" -m pip install graphifyy tree-sitter-css==0.25.0 PyYAML==6.0.3 >&2
    tool_bin="$tool_root/bin"
fi
graphify_bin="$tool_bin/graphify"
if [[ ! -x "$graphify_bin" ]]; then
    printf '%s\n' "Graphify não foi encontrado após a instalação. Confira uv/pipx e o PATH." >&2
    exit 1
fi
"$graphify_bin" --version >&2
printf '%s\n' "$graphify_bin"
