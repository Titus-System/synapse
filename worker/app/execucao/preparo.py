"""Monta o payload de execução a partir do comando e do código lido do Postgres."""

from dataclasses import dataclass
from uuid import UUID

from app.mensageria.contracts import ExecutarCodigo
from app.repositorio.codigos_gerados import CodigoGerado


@dataclass(frozen=True)
class PayloadContainer:
    """Vai para dentro do sandbox — nunca o orçamento (ver `ExecucaoPreparada`)."""

    job_id: UUID
    codigo_gerado_id: UUID
    linguagem: str
    fonte: str
    competencias: list[str]


@dataclass(frozen=True)
class ExecucaoPreparada:
    """`orcamento` fica fora de `payload`: o veredito é decidido pelo processo do
    worker, nunca dentro do container que roda o código não confiável."""

    payload: PayloadContainer
    orcamento: float


def preparar_execucao(comando: ExecutarCodigo, codigo: CodigoGerado) -> ExecucaoPreparada:
    payload = PayloadContainer(
        job_id=comando.job_id,
        codigo_gerado_id=codigo.id,
        linguagem=codigo.linguagem,
        fonte=codigo.fonte,
        competencias=comando.competencias,
    )
    return ExecucaoPreparada(payload=payload, orcamento=comando.orcamento)
