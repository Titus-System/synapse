"""Valida o resultado que saiu do container contra o schema da T-034, e o diagnóstico que o
worker grava quando ele falha (T-204).

A validação roda no processo do worker, fora do container: a imagem do sandbox só admite
pandas e a biblioteca padrão, e quem escreveu o resultado é código não confiável, que não
pode ser também quem o valida.

Os schemas vêm de ``contracts/``, que o build copia para dentro da imagem (ADR-002: insumo
de build, nunca pacote importado). O módulo procura o diretório subindo a partir de si, o
que serve ao repositório (``<raiz>/contracts``) e à imagem (``/app/contracts``).
"""

import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ESQUEMA_RESULTADO = "resultado-simulacao.schema.json"
ESQUEMA_ASSERCOES = "resultado-assercoes.schema.json"
ESQUEMA_DIAGNOSTICO = "resultado-diagnostico.schema.json"
ESQUEMA_LINHAS = "resultado-linhas.schema.json"


class Problema(TypedDict):
    """Onde um valor falhou num schema: o caminho e a palavra-chave que o reprovou, nunca o valor.

    É o item de ``problemas`` em ``resultado-diagnostico.schema.json``. As chaves do caminho vêm do
    que foi validado, e no resultado do container são dado não confiável.
    """

    caminho: str
    palavra_chave: str


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
    validador(ESQUEMA_DIAGNOSTICO)
    validador(ESQUEMA_LINHAS)


def validar_linhas(linhas: object, competencias: Sequence[str]) -> list[Problema]:
    """Valida a forma e o período; conferência dos valores pertence à T-262.

    Caminhos do validador contêm chaves arbitrárias do container (inclusive matrícula).
    O diagnóstico e os logs levam somente a raiz estática e a classe do erro.
    """
    palavras = {str(erro.validator) for erro in validador(ESQUEMA_LINHAS).iter_errors(linhas)}
    if isinstance(linhas, dict) and set(linhas) != set(competencias):
        palavras.add("competencias_divergentes")
    return [Problema(caminho="$.linhas", palavra_chave=p) for p in sorted(palavras)]


def validar_resultado(resultado: Mapping[str, Any], orcamento: float | None) -> list[Problema]:
    """Erros do resultado contra ``resultado-simulacao.schema.json`` (vazio = válido).

    O container não recebe o orçamento, então ``totais`` chega sem ``orcamento``. Com
    orçamento, a validação vê uma **cópia** com o orçamento do worker acrescentado, a forma que
    será gravada; sem ele (job sem orçamento), vê os totais como vieram. ``resultado`` não é
    alterado, e é ele que segue adiante. Um ``totais.orcamento`` já presente na saída é
    reprovado nos dois casos: o harness não o produz, então alguém o fabricou, e ele não pode
    chegar ao veredito, nem à linha de um job sem orçamento, parecendo dado do container.

    Cada problema é o caminho e a palavra-chave do schema, nunca o valor nem a mensagem do
    validador: o conteúdo veio de código não confiável e não pode chegar a um log.
    """
    candidato: dict[str, Any] = dict(resultado)
    fabricado = False
    totais = candidato.get("totais")
    if isinstance(totais, Mapping):
        fabricado = "orcamento" in totais
        candidato["totais"] = {k: v for k, v in totais.items() if k != "orcamento"}
        if orcamento is not None:
            candidato["totais"]["orcamento"] = orcamento
    erros = _erros(validador(ESQUEMA_RESULTADO), candidato)
    if fabricado:
        erros.insert(
            0, Problema(caminho="$.totais.orcamento", palavra_chave="fornecido_pelo_container")
        )
    return erros


def validar_assercoes(assercoes: object) -> list[Problema]:
    """Erros de uma lista de desfechos contra ``resultado-assercoes.schema.json``."""
    return _erros(validador(ESQUEMA_ASSERCOES), assercoes)


def validar_diagnostico(diagnostico: Mapping[str, object]) -> list[Problema]:
    """Erros do diagnóstico montado pelo worker contra ``resultado-diagnostico.schema.json``."""
    return _erros(validador(ESQUEMA_DIAGNOSTICO), diagnostico)


def _erros(esquema: Draft202012Validator, instancia: object) -> list[Problema]:
    erros = sorted(
        esquema.iter_errors(instancia),
        key=lambda erro: tuple(str(parte) for parte in erro.absolute_path),
    )
    return [
        Problema(caminho=_caminho(list(erro.absolute_path)), palavra_chave=str(erro.validator))
        for erro in erros
    ]


def _caminho(partes: list[Any]) -> str:
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in partes)
