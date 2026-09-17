from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


DIRETORIO_CONTRATOS = Path(__file__).resolve().parent
DIRETORIO_EXEMPLOS = DIRETORIO_CONTRATOS / "examples"
ARQUIVO_MANIFESTO = DIRETORIO_EXEMPLOS / "manifesto.json"
DIRETORIOS_ESQUEMAS = (DIRETORIO_CONTRATOS / "domain", DIRETORIO_CONTRATOS / "events")


def carregar_json(caminho: Path) -> Any:
    with caminho.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)


def carregar_esquemas() -> dict[str, dict[str, Any]]:
    esquemas: dict[str, dict[str, Any]] = {}
    for diretorio in DIRETORIOS_ESQUEMAS:
        for caminho in sorted(diretorio.glob("*.schema.json")):
            caminho_relativo = caminho.relative_to(DIRETORIO_CONTRATOS).as_posix()
            esquemas[caminho_relativo] = carregar_json(caminho)
    return esquemas


def criar_registro(esquemas: dict[str, dict[str, Any]]) -> Registry:
    registro = Registry()
    for esquema in esquemas.values():
        identificador = esquema.get("$id")
        if not isinstance(identificador, str):
            raise ValueError("Todo esquema deve declarar um $id textual.")
        recurso = Resource.from_contents(esquema, default_specification=DRAFT202012)
        registro = registro.with_resource(identificador, recurso)
    return registro


def formatar_caminho(caminho: list[Any]) -> str:
    partes = ["$"]
    for parte in caminho:
        partes.append(f"[{parte}]" if isinstance(parte, int) else f".{parte}")
    return "".join(partes)


def carregar_manifesto() -> dict[str, str]:
    conteudo = carregar_json(ARQUIVO_MANIFESTO)
    exemplos = conteudo.get("exemplos") if isinstance(conteudo, dict) else None
    if not isinstance(exemplos, dict) or not all(
        isinstance(caminho, str) and isinstance(esquema, str)
        for caminho, esquema in exemplos.items()
    ):
        raise ValueError('O manifesto deve conter o objeto textual "exemplos".')
    return exemplos


def validar_cobertura(exemplos: dict[str, str], esquemas: dict[str, dict[str, Any]]) -> list[str]:
    erros: list[str] = []
    esquemas_sem_exemplo = sorted(set(esquemas) - set(exemplos.values()))
    if esquemas_sem_exemplo:
        erros.append("esquemas sem exemplo: " + ", ".join(esquemas_sem_exemplo))

    caminhos_esperados = {
        caminho.relative_to(DIRETORIO_EXEMPLOS).as_posix()
        for caminho in DIRETORIO_EXEMPLOS.rglob("*.json")
        if caminho != ARQUIVO_MANIFESTO
    }
    caminhos_declarados = set(exemplos)
    if caminhos_sem_esquema := sorted(caminhos_esperados - caminhos_declarados):
        erros.append("exemplos ausentes no manifesto: " + ", ".join(caminhos_sem_esquema))
    if caminhos_inexistentes := sorted(caminhos_declarados - caminhos_esperados):
        erros.append("exemplos inexistentes: " + ", ".join(caminhos_inexistentes))
    if esquemas_inexistentes := sorted(set(exemplos.values()) - set(esquemas)):
        erros.append("esquemas inexistentes no manifesto: " + ", ".join(esquemas_inexistentes))
    return erros


def validar_exemplos() -> int:
    try:
        esquemas = carregar_esquemas()
        exemplos = carregar_manifesto()
        registro = criar_registro(esquemas)
    except (OSError, ValueError, json.JSONDecodeError) as erro:
        print(f"ERRO ao preparar a validação: {erro}", file=sys.stderr)
        return 1

    erros = validar_cobertura(exemplos, esquemas)
    for caminho_exemplo, caminho_esquema in sorted(exemplos.items()):
        try:
            exemplo = carregar_json(DIRETORIO_EXEMPLOS / caminho_exemplo)
        except (OSError, json.JSONDecodeError) as erro:
            erros.append(f"{caminho_exemplo}: não foi possível ler o exemplo: {erro}")
            continue

        validador = Draft202012Validator(
            esquemas[caminho_esquema], registry=registro, format_checker=FormatChecker()
        )
        for erro in sorted(
            validador.iter_errors(exemplo),
            key=lambda erro_validacao: tuple(
                str(parte) for parte in erro_validacao.absolute_path
            ),
        ):
            campo = formatar_caminho(list(erro.absolute_path))
            erros.append(f"{caminho_exemplo}: campo {campo}: {erro.message}")

    if erros:
        print("Exemplos de contrato inválidos:", file=sys.stderr)
        for erro in erros:
            print(f"- {erro}", file=sys.stderr)
        return 1

    print(f"{len(exemplos)} exemplos validados contra {len(esquemas)} esquemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(validar_exemplos())
