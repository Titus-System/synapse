from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import OpenAPIV31SpecValidator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


DIRETORIO_CONTRATOS = Path(__file__).resolve().parent
DIRETORIO_EXEMPLOS = DIRETORIO_CONTRATOS / "examples"
ARQUIVO_MANIFESTO = DIRETORIO_EXEMPLOS / "manifesto.json"
ARQUIVO_OPENAPI = DIRETORIO_CONTRATOS / "http" / "openapi.yaml"
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
    for caminho, esquema in esquemas.items():
        identificador = esquema.get("$id")
        if not isinstance(identificador, str):
            raise ValueError("Todo esquema deve declarar um $id textual.")
        recurso = Resource.from_contents(esquema, default_specification=DRAFT202012)
        registro = registro.with_resource(identificador, recurso)
        registro = registro.with_resource((DIRETORIO_CONTRATOS / caminho).as_uri(), recurso)
    return registro


def percorrer_documento(no: Any, ponteiro: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(no, dict):
        yield ponteiro, no
        for chave, valor in no.items():
            if chave not in {"example", "examples", "default"}:
                segmento = chave.replace("~", "~0").replace("/", "~1")
                yield from percorrer_documento(valor, f"{ponteiro}/{segmento}")
    elif isinstance(no, list):
        for indice, valor in enumerate(no):
            yield from percorrer_documento(valor, f"{ponteiro}/{indice}")


def validar_openapi(registro: Registry) -> tuple[list[str], int]:
    with ARQUIVO_OPENAPI.open(encoding="utf-8") as arquivo:
        documento = yaml.safe_load(arquivo)
    uri = ARQUIVO_OPENAPI.as_uri()
    erros = [
        f"http/openapi.yaml: campo {formatar_caminho(list(erro.absolute_path))}: {erro.message}"
        for erro in OpenAPIV31SpecValidator(documento, base_uri=uri).iter_errors()
    ]
    if erros:
        return erros, 0

    registro = registro.with_resource(
        uri, Resource.from_contents(documento, default_specification=DRAFT202012)
    )
    quantidade = 0
    for ponteiro, no in percorrer_documento(documento):
        exemplos: list[tuple[str, Any]] = []
        if isinstance(no.get("examples"), list):
            exemplos.extend(
                (str(indice), valor) for indice, valor in enumerate(no["examples"])
            )
        elif "schema" in no:
            for nome, exemplo in no.get("examples", {}).items():
                if "$ref" in exemplo:
                    exemplo = registro.resolver(uri).lookup(exemplo["$ref"]).contents
                exemplos.append((nome, exemplo["value"]))
        if "example" in no:
            exemplos.append(("example", no["example"]))

        if not exemplos:
            continue
        if ponteiro.endswith("/content/text~1event-stream"):
            eventos: list[tuple[str, Any]] = []
            for nome, stream in exemplos:
                for indice, bloco in enumerate(stream.split("\n\n")):
                    dados = "\n".join(
                        linha.removeprefix("data:").lstrip(" ")
                        for linha in bloco.splitlines()
                        if linha.startswith("data:")
                    )
                    if dados:
                        eventos.append((f"{nome}[{indice}]", json.loads(dados)))
            exemplos = eventos
        referencia = f"{uri}#{ponteiro}"
        if "schema" in no:
            referencia += "/schema"
        validador = Draft202012Validator(
            {"$ref": referencia}, registry=registro, format_checker=FormatChecker()
        )
        for nome, exemplo in exemplos:
            quantidade += 1
            for erro in validador.iter_errors(exemplo):
                campo = formatar_caminho(list(erro.absolute_path))
                erros.append(
                    f"http/openapi.yaml#{ponteiro}: exemplo {nome}, campo {campo}: {erro.message}"
                )
    return erros, quantidade


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

    try:
        erros_http, quantidade_http = validar_openapi(registro)
        erros.extend(erros_http)
    except Exception as erro:
        print(f"ERRO ao validar http/openapi.yaml: {erro}", file=sys.stderr)
        return 1

    if erros:
        print("Exemplos de contrato inválidos:", file=sys.stderr)
        for erro in erros:
            print(f"- {erro}", file=sys.stderr)
        return 1

    print(f"{len(exemplos)} exemplos validados contra {len(esquemas)} esquemas.")
    print(f"OpenAPI 3.1 válido; {quantidade_http} exemplos HTTP validados por referência.")
    return 0


if __name__ == "__main__":
    raise SystemExit(validar_exemplos())
