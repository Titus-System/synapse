"""DTOs das mensagens de RabbitMQ usadas pelo worker."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MensagemBase(BaseModel):
    """Base compatível com a evolução aditiva dos contratos."""

    model_config = ConfigDict(extra="ignore")


class ExecutarCodigo(MensagemBase):
    """Comando recebido pelo worker para executar uma regra gerada."""

    job_id: UUID
    codigo_gerado_id: UUID
    competencias: list[str] = Field(min_length=1)
    orcamento: float = Field(ge=0)


class SimulacaoConcluida(MensagemBase):
    """Evento publicado pelo worker depois da execução da simulação."""

    job_id: UUID
    resultado_id: UUID
    status: Literal["sucesso", "assercao_violada", "erro_codigo", "erro_infra"]
    veredito: Literal["viavel", "inviavel", "indeterminado"] | None = None
    total_baseline: float | None = None
    total_simulado: float | None = None
    diferenca_abs: float | None = None
    diferenca_pct: float | None = None
