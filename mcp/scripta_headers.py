#!/usr/bin/env python3
"""Saída exclusiva para http_headers_helper do Codex; não executar em logs."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def headers(root=ROOT):
    path = root.parent / "scripta-token"
    if root.parent.name != ".gag-dev-team" or path.is_symlink():
        raise ValueError("Configure o Scripta pelo comando configure.")
    token = path.read_text(encoding="utf-8").strip()
    if not token or len(token) > 4096 or any(c in token for c in ("\r", "\n", "\0")):
        raise ValueError("Chave Scripta inválida; use configure.")
    return {"Authorization": "Bearer " + token}


if __name__ == "__main__":
    try:
        print(json.dumps(headers()))
    except (OSError, ValueError):
        print("Configure a chave do Scripta com gag-dev-team configure.", file=sys.stderr)
        sys.exit(1)
