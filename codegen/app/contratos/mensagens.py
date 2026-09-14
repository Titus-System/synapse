from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModeloContrato(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OrigemJob(StrEnum):
    FORMULARIO = "formulario"
    VOZ = "voz"
    REPROCESSAMENTO = "reprocessamento"


class StatusSimulacao(StrEnum):
    SUCESSO = "sucesso"
    ASSERCAO_VIOLADA = "assercao_violada"
    ERRO_CODIGO = "erro_codigo"
    ERRO_INFRA = "erro_infra"


class Veredito(StrEnum):
    VIAVEL = "viavel"
    INVIAVEL = "inviavel"
    INDETERMINADO = "indeterminado"


NoGrafo = Literal[
    "extracao_parametros",
    "validacao_dominio",
    "confirmacao",
    "geracao_codigo",
    "delegacao_worker",
    "interpretacao_resultado",
    "decisao",
    "explicacao",
]


class RegraSubmetida(ModeloContrato):
    job_id: UUID
    origem: OrigemJob
    competencias: list[str] = Field(min_length=1)
    submissao_id: UUID | None = None
    regra_id: UUID | None = None


class ParametrosConfirmados(ModeloContrato):
    job_id: UUID
    regra_id: UUID


class SimulacaoConcluida(ModeloContrato):
    job_id: UUID
    resultado_id: UUID
    status: StatusSimulacao
    veredito: Veredito | None = None
    total_baseline: Decimal | None = None
    total_simulado: Decimal | None = None
    diferenca_abs: Decimal | None = None
    diferenca_pct: Decimal | None = None


class ExecutarCodigo(ModeloContrato):
    job_id: UUID
    codigo_gerado_id: UUID
    competencias: list[str] = Field(min_length=1)
    orcamento: Decimal = Field(ge=0)


class EtapaAlterada(ModeloContrato):
    job_id: UUID
    etapa: NoGrafo
    status: str = Field(min_length=1)


class NoConcluido(ModeloContrato):
    evento_id: UUID
    job_id: UUID
    no: NoGrafo
    concluido_em: datetime
    conclusao: dict[str, object]
    regra_id: UUID | None = None
    simulacao_id: UUID | None = None
    prompt_id: UUID | None = None
    codigo_gerado_id: UUID | None = None
    explicacao_id: UUID | None = None
