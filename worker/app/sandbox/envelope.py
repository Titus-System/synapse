"""Envelope que o sandbox escreve no stdout (T-033).

Fronteira interna entre a imagem do sandbox e o worker, ambos do mesmo componente,
por isso vive aqui e não em ``contracts/``. Só dados e serialização: não importa
pandas nem executa código gerado, então o worker (T-064) pode importá-lo sem tocar no
caminho que roda regra não confiável.

O container nunca emite ``erro_infra``. Falha de subir, timeout e morte por memória
são decididas fora dele (T-065); um container que não produz envelope não se
autodeclara quebrado, ele apenas falha em voz alta no stderr.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal, TypedDict

from app.sandbox.assercoes import Desfecho
from app.sandbox.resultado import ResultadoSimulacao

VERSAO = 1

# O payload que o worker escreve no stdin: exatamente os campos de PayloadContainer
# (app/execucao/preparo.py). Nunca ``orcamento``: quem produz o número não alcança o
# critério que vai julgá-lo (T-066). Um teste confere que as duas listas não divergem.
CAMPOS_PAYLOAD = frozenset({"job_id", "codigo_gerado_id", "linguagem", "fonte", "competencias"})

type Status = Literal["sucesso", "assercao_violada", "erro_codigo"]

# Vocabulário de resultados_simulacao.status e de simulacao-concluida.schema.json,
# menos ``erro_infra``.
SAIDA_SUCESSO = 0
# 1 é o código que o Python devolve para exceção não tratada. Ele significa "o próprio
# harness ou o dado embutido falhou, sem envelope", nunca culpa do código gerado: assim
# uma falha inesperada nunca é atribuída à regra por engano.
SAIDA_HARNESS = 1
SAIDA_ASSERCAO_VIOLADA = 2
SAIDA_ERRO_CODIGO = 3
# 128 + 15: o executor foi encerrado por SIGTERM (`docker stop`), sem envelope. 137 (128 + 9)
# também sai sem envelope, mas quem o devolve é o Docker: SIGKILL de `docker kill` ou
# estouro de memória. Nenhum dos dois é veredito do código gerado.
SAIDA_SIGTERM = 143

SAIDA_POR_STATUS: Mapping[Status, int] = {
    "sucesso": SAIDA_SUCESSO,
    "assercao_violada": SAIDA_ASSERCAO_VIOLADA,
    "erro_codigo": SAIDA_ERRO_CODIGO,
}

LIMITE_MENSAGEM = 1000
LIMITE_TRACEBACK = 8000


class Falha(TypedDict):
    """Conteúdo de erro vindo do código gerado: dado não confiável.

    Quem consome trata como texto, nunca como instrução, e não o registra em log.
    """

    tipo: str
    mensagem: str
    traceback: str


class Envelope(TypedDict):
    versao: int
    job_id: str
    codigo_gerado_id: str
    competencias: list[str]
    status: Status
    # Cópia de resultado.assercoes, para existir também quando resultado é nulo.
    assercoes: list[Desfecho]
    # Só em sucesso. Válido contra resultado-simulacao.schema.json quando o worker
    # acrescenta totais.orcamento.
    resultado: ResultadoSimulacao | None
    # Só em erro_codigo.
    erro: Falha | None


def serializar(envelope: Envelope) -> str:
    """Uma linha de JSON, determinística: o mesmo payload produz os mesmos bytes."""
    return json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
