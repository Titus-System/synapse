"""Ponto de entrada da imagem do sandbox (T-033).

Lê um payload do stdin, executa a função gerada sobre as bases embutidas e escreve um
envelope de uma linha no stdout. Nenhum volume, nenhum arquivo de trabalho, nenhuma rede.

Códigos de saída (ver ``envelope.py``): 0 sucesso, 2 asserção violada e 3 erro no código
gerado escrevem envelope; 1 é falha do próprio harness ou do dado embutido, sem envelope
e com o motivo no stderr.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import traceback
from pathlib import Path
from typing import BinaryIO, NamedTuple

from app.sandbox.carga import RAIZ_DADOS, CargaError, Entrada, carregar
from app.sandbox.envelope import (
    CAMPOS_PAYLOAD,
    LIMITE_MENSAGEM,
    LIMITE_TRACEBACK,
    SAIDA_HARNESS,
    SAIDA_POR_STATUS,
    SAIDA_SIGTERM,
    VERSAO,
    Envelope,
    Falha,
    Status,
    serializar,
)
from app.sandbox.harness import NOME_ARQUIVO, Execucao, agregar, rodar_regra
from app.sandbox.resultado import ResultadoInvalidoError

LINGUAGEM = "python"


class PayloadInvalidoError(ValueError):
    """O que o worker escreveu no stdin não é um payload válido."""


class Payload(NamedTuple):
    job_id: str
    codigo_gerado_id: str
    competencias: tuple[str, ...]
    fonte: str


def ler_payload(dados: bytes) -> Payload:
    """Lê o payload como UTF-8 explícito.

    O modo texto faria a decodificação depender do locale do container, que na imagem
    base não vem definido: uma regra com acento no docstring poderia chegar corrompida
    ao ``compile`` ou estourar ``UnicodeDecodeError`` conforme a coerção de locale.
    """
    try:
        bruto = json.loads(dados.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as erro:
        raise PayloadInvalidoError(f"o stdin não é um JSON em UTF-8: {erro}") from erro
    if not isinstance(bruto, dict):
        raise PayloadInvalidoError("o payload deve ser um objeto JSON")

    # Campo desconhecido é recusado, não ignorado. O caso que importa é ``orcamento``:
    # se um dia chegar aqui, é falha do worker, e falhar em voz alta é o que impede o
    # critério de julgamento de entrar onde o número é produzido.
    extras = bruto.keys() - CAMPOS_PAYLOAD
    faltando = CAMPOS_PAYLOAD - bruto.keys()
    if extras or faltando:
        raise PayloadInvalidoError(
            f"campos do payload divergem do contrato: sobram {sorted(extras)}, "
            f"faltam {sorted(faltando)}"
        )
    if bruto["linguagem"] != LINGUAGEM:
        raise PayloadInvalidoError(f"linguagem deve ser {LINGUAGEM!r}")
    for campo in ("job_id", "codigo_gerado_id", "fonte"):
        if not isinstance(bruto[campo], str) or not bruto[campo]:
            raise PayloadInvalidoError(f"{campo} deve ser texto não vazio")
    competencias = bruto["competencias"]
    if (
        not isinstance(competencias, list)
        or not competencias
        or not all(isinstance(competencia, str) for competencia in competencias)
    ):
        raise PayloadInvalidoError("competencias deve ser uma lista não vazia de textos")
    return Payload(
        job_id=bruto["job_id"],
        codigo_gerado_id=bruto["codigo_gerado_id"],
        competencias=tuple(competencias),
        fonte=bruto["fonte"],
    )


def processar(entrada: BinaryIO, saida: BinaryIO, *, raiz: Path = RAIZ_DADOS) -> int:
    """Executa um payload e escreve o envelope. Devolve o código de saída do processo."""
    try:
        payload = ler_payload(entrada.read())
        dados = carregar(payload.competencias, raiz=raiz)
    except (PayloadInvalidoError, CargaError) as erro:
        print(f"falha do harness: {erro}", file=sys.stderr)
        return SAIDA_HARNESS

    competencias = list(payload.competencias)
    status, execucao, falha = _rodar(payload.fonte, dados, competencias)

    envelope = Envelope(
        versao=VERSAO,
        job_id=payload.job_id,
        codigo_gerado_id=payload.codigo_gerado_id,
        competencias=competencias,
        status=status,
        assercoes=execucao.assercoes if execucao else [],
        resultado=execucao.resultado if execucao else None,
        erro=falha,
    )
    saida.write(serializar(envelope).encode("utf-8") + b"\n")
    saida.flush()
    return SAIDA_POR_STATUS[status]


def _rodar(
    fonte: str, dados: Entrada, competencias: list[str]
) -> tuple[Status, Execucao | None, Falha | None]:
    try:
        tabelas = rodar_regra(fonte, dados, competencias)
    # SystemExit não é Exception: uma regra que chama sys.exit() sairia do processo com
    # código 0 e sem envelope, e pareceria sucesso para quem só olha o código de saída.
    except (Exception, SystemExit) as erro:
        return "erro_codigo", None, _falha(erro)
    try:
        execucao = agregar(tabelas, dados, competencias)
    except ResultadoInvalidoError as erro:
        # A saída do código gerado não sustenta o resultado. Qualquer OUTRA exceção
        # daqui é bug do harness: sobe para main e vira código 1, nunca culpa da regra.
        return "erro_codigo", None, _falha(erro)
    return ("sucesso" if execucao.resultado is not None else "assercao_violada"), execucao, None


def _falha(erro: BaseException) -> Falha:
    """Só os quadros da própria regra: o resto é do harness e não ajuda quem a escreveu."""
    quadros = [q for q in traceback.extract_tb(erro.__traceback__) if q.filename == NOME_ARQUIVO]
    try:
        mensagem = str(erro)
    except Exception:  # __str__ de exceção vinda do código gerado pode levantar
        mensagem = "<mensagem ilegível>"
    return Falha(
        tipo=type(erro).__name__[:100],
        mensagem=mensagem[:LIMITE_MENSAGEM],
        traceback="".join(traceback.format_list(quadros))[-LIMITE_TRACEBACK:],
    )


def _reservar_canal_de_saida() -> BinaryIO:
    """Separa o canal do envelope de tudo que o código gerado possa escrever.

    O ``print()`` de uma regra iria para o stdout e se misturaria ao JSON; o mesmo vale
    para um subprocesso ou uma biblioteca em C que escreva direto no descritor 1. Por
    isso o descritor 1 é duplicado para o envelope e depois apontado para o stderr.
    """
    sys.stdout.flush()
    canal = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    return canal


def _encerrar_ao_receber_sigterm() -> None:
    """Faz o ``docker stop`` valer.

    O executor é o PID 1 do container, e o kernel não entrega a um PID 1 um sinal sem
    handler: sem isto o SIGTERM seria ignorado e o container só morreria pelo SIGKILL ao
    fim do prazo do ``stop`` (10 s por padrão). ``os._exit`` e não ``SystemExit``, porque
    a regra pode capturar ``SystemExit`` e continuar rodando.
    """
    signal.signal(signal.SIGTERM, lambda *_: os._exit(SAIDA_SIGTERM))


def main() -> int:
    _encerrar_ao_receber_sigterm()
    canal = _reservar_canal_de_saida()
    try:
        return processar(sys.stdin.buffer, canal)
    except BaseException:  # qualquer escape aqui é falha do harness, não da regra
        traceback.print_exc()
        return SAIDA_HARNESS


if __name__ == "__main__":
    raise SystemExit(main())
