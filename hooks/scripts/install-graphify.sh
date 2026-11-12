#!/usr/bin/env bash
# Fonte: https://github.com/Graphify-Labs/graphify#install
# stdout: somente o caminho do executável; diagnósticos vão para stderr.
set -euo pipefail
export PATH="${HOME}/.local/bin:${PATH}"
if command -v graphify >/dev/null 2>&1; then
    graphify --version >&2
    command -v graphify
    exit 0
fi
if command -v uv >/dev/null 2>&1; then
    uv tool install graphifyy >&2
    tool_bin="$(uv tool dir --bin)"
elif command -v pipx >/dev/null 2>&1; then
    pipx install graphifyy >&2
    tool_bin="$(pipx environment --value PIPX_BIN_DIR)"
else
    # Ambiente isolado: não altera o Python do sistema.
    python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ obrigatório"' >&2
    tool_root="${PLUGIN_DATA:-${XDG_DATA_HOME:-${HOME}/.local/share}/gag-dev-team-plugin}/graphify-venv"
    python3 -m venv "$tool_root" >&2
    "$tool_root/bin/python" -m pip install graphifyy >&2
    tool_bin="$tool_root/bin"
fi
graphify_bin="$tool_bin/graphify"
if [[ ! -x "$graphify_bin" ]]; then
    printf '%s\n' "Graphify não foi encontrado após a instalação. Confira uv/pipx e o PATH." >&2
    exit 1
fi
"$graphify_bin" --version >&2
printf '%s\n' "$graphify_bin"
