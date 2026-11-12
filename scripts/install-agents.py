#!/usr/bin/env python3
"""Instala perfis do pacote no projeto, preservando configurações diferentes."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install(project, source=ROOT / "agents"):
    project = Path(project).resolve(strict=True)
    if not project.is_dir():
        raise ValueError("O destino deve ser a raiz de um projeto existente.")
    target = project / ".codex" / "agents"
    if not target.resolve().is_relative_to(project):
        raise ValueError("O diretório .codex/agents deve permanecer dentro do projeto.")
    profiles = sorted(source.glob("gag-*.toml"))
    if len(profiles) != 5:
        raise ValueError("O pacote deve conter os cinco perfis do GAG Dev Team.")
    # Verificar todos antes de escrever: colisão não deixa instalação parcial.
    for profile in profiles:
        destination = target / profile.name
        if destination.is_symlink():
            raise ValueError(f"Perfil de destino é um link simbólico: {destination.name}")
        if destination.exists() and destination.read_bytes() != profile.read_bytes():
            raise ValueError(f"Perfil existente diferente; preserve e resolva a configuração: {destination.name}")
    target.mkdir(parents=True, exist_ok=True)
    for profile in profiles:
        destination = target / profile.name
        if not destination.exists():
            # Criação exclusiva evita sobrescrever um arquivo criado após a checagem.
            with destination.open("xb") as output:
                output.write(profile.read_bytes())
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Raiz absoluta do projeto de destino")
    args = parser.parse_args()
    try:
        target = install(args.project)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Não foi possível instalar os perfis: {error}\n")
    print(f"Cinco perfis disponíveis em {target}. Reinicie a sessão do Codex para recarregar.")
