"""Valida o resultado que saiu do container contra o schema da T-034.

A validação roda no processo do worker, fora do container: a imagem do sandbox só admite
pandas e a biblioteca padrão, e quem escreveu o resultado é código não confiável, que não
pode ser também quem o valida.

Os schemas vêm de ``contracts/``, que o build copia para dentro da imagem (ADR-002: insumo
de build, nunca pacote importado). O módulo procura o diretório subindo a partir de si, o
que serve ao repositório (``<raiz>/contracts``) e à imagem (``/app/contracts``).
"""

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ESQUEMA_RESULTADO = "resultado-simulacao.schema.json"
ESQUEMA_ASSERCOES = "resultado-assercoes.schema.json"


class ContratosIndisponiveisError(RuntimeError):
    """``contracts/domain`` não está ao alcance do processo: a imagem foi montada sem ele."""


def _diretorio_domain() -> Path:
    for pai in Path(__file__).resolve().parents:
        candidato = pai / "contracts" / "domain"
        if candidato.is_dir():
            return candidato
    raise ContratosIndisponiveisError("contracts/domain não encontrado a partir de app/execucao")


@lru_cache
def validador(nome: str = ESQUEMA_RESULTADO) -> Draft202012Validator:
    """Carrega um schema de ``contracts/domain`` (uma vez por nome). A subida do processo
    chama ``carregar_contratos``, para que um ``contracts/`` ausente derrube o worker ali, e
    não no primeiro job."""
    diretorio = _diretorio_domain()
    esquemas = [
        json.loads(arquivo.read_text(encoding="utf-8"))
        for arquivo in sorted(diretorio.glob("*.schema.json"))
    ]
    registro: Registry[Any] = Registry().with_resources(
        (esquema["$id"], Resource.from_contents(esquema, default_specification=DRAFT202012))
        for esquema in esquemas
    )
    raiz = next((esquema for esquema in esquemas if esquema["$id"].endswith(f"/{nome}")), None)
    if raiz is None:
        raise ContratosIndisponiveisError(f"{nome} não encontrado em {diretorio}")
    return Draft202012Validator(raiz, registry=registro, format_checker=FormatChecker())


def carregar_contratos() -> None:
    """Falha na subida, e não no primeiro job, se algum schema usado não estiver ao alcance."""
    validador(ESQUEMA_RESULTADO)
    validador(ESQUEMA_ASSERCOES)


def validar_resultado(resultado: Mapping[str, Any], orcamento: float) -> list[str]:
    """Erros do resultado contra ``resultado-simulacao.schema.json`` (vazio = válido).

    O container não recebe o orçamento, então ``totais`` chega sem ``orcamento`` e o schema,
    que o exige, reprovaria todo resultado. A validação vê uma **cópia** com o orçamento do
    worker acrescentado; ``resultado`` não é alterado, e é ele que segue adiante. Um
    ``totais.orcamento`` já presente na saída é reprovado: o harness não o produz, então
    alguém o fabricou, e ele não pode chegar ao veredito parecendo dado do container.

    Cada erro é ``<caminho>: <palavra-chave do schema>``, nunca o valor nem a mensagem do
    validador: o conteúdo veio de código não confiável e não pode chegar a um log.
    """
    candidato: dict[str, Any] = dict(resultado)
    fabricado = False
    totais = candidato.get("totais")
    if isinstance(totais, Mapping):
        fabricado = "orcamento" in totais
        candidato["totais"] = {**totais, "orcamento": orcamento}
    erros = _erros(validador(ESQUEMA_RESULTADO), candidato)
    if fabricado:
        erros.insert(0, "$.totais.orcamento: fornecido_pelo_container")
    return erros


def validar_assercoes(assercoes: object) -> list[str]:
    """Erros de uma lista de desfechos contra ``resultado-assercoes.schema.json``."""
    return _erros(validador(ESQUEMA_ASSERCOES), assercoes)


def _erros(esquema: Draft202012Validator, instancia: object) -> list[str]:
    erros = sorted(
        esquema.iter_errors(instancia),
        key=lambda erro: tuple(str(parte) for parte in erro.absolute_path),
    )
    return [f"{_caminho(list(erro.absolute_path))}: {erro.validator}" for erro in erros]


def _caminho(partes: list[Any]) -> str:
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in partes)
