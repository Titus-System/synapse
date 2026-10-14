"""Escolha determinística de metas; todos os custos são apurados pelo worker."""

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from typing import Literal

# O sandbox admite 60 s por execução: doze candidatas limitam seu trabalho a 720 s,
# fora fila, reapuração do baseline e transporte. Não é um SLA de tempo total.
LIMITE_CANDIDATOS = 12
TOLERANCIA_RELATIVA = Decimal("0.001")
MotivoSemSolucao = Literal["nao_monotonica", "intervalo_esgotado", "falha_execucao"]


@dataclass(frozen=True)
class Ponto:
    meta: Decimal
    comissao: Decimal
    resultado_id: str


@dataclass(frozen=True)
class Passo:
    candidata: Decimal | None = None
    vencedora: Ponto | None = None
    motivo: MotivoSemSolucao | None = None


def escolher(pontos: list[Ponto], orcamento: Decimal) -> Passo:
    """Expande e estreita o intervalo, sem atribuir viabilidade a uma estimativa."""
    ordenados = sorted(pontos, key=lambda p: p.meta)
    if any(a.comissao > b.comissao for a, b in pairwise(ordenados)):
        return Passo(motivo="nao_monotonica")
    inicial = pontos[0]
    inferiores = [p for p in ordenados if p.comissao <= orcamento]
    superiores = [p for p in ordenados if p.comissao > orcamento]
    inferior = inferiores[-1]
    superior = superiores[0] if superiores else None
    limite = len(pontos) - 1 >= LIMITE_CANDIDATOS
    if superior is not None:
        estreito = superior.meta - inferior.meta <= inferior.meta * TOLERANCIA_RELATIVA
        if (estreito or limite) and inferior.meta > inicial.meta:
            return Passo(vencedora=inferior)
        candidata = (inferior.meta + superior.meta) / 2
    elif limite:
        return Passo(motivo="intervalo_esgotado")
    elif len(pontos) == 1 and inicial.comissao > 0:
        candidata = inicial.meta * orcamento / inicial.comissao
    else:
        candidata = inferior.meta * 2
    # O worker persiste Decimal(str(meta)) depois de ler a meta como float.
    # Canonicalizar antes do envio mantém a identidade da candidata na retomada.
    candidata = Decimal(str(float(candidata)))
    if limite or candidata <= inferior.meta or (superior and candidata >= superior.meta):
        # Sem uma execução maior viável, não há resultado que a API possa oferecer.
        return Passo(motivo="intervalo_esgotado")
    return Passo(candidata=candidata)
