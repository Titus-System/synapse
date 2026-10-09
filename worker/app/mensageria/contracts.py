"""DTOs das mensagens de RabbitMQ usadas pelo worker."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.sandbox.resultado import PADRAO_ELEMENTO_REF

ReferenciaDeElemento = Annotated[str, Field(pattern=PADRAO_ELEMENTO_REF.pattern)]


class MensagemBase(BaseModel):
    """Base compatível com a evolução aditiva dos contratos."""

    model_config = ConfigDict(extra="ignore")


class ExecutarCodigo(MensagemBase):
    """Comando recebido pelo worker para executar uma regra gerada."""

    job_id: UUID
    codigo_gerado_id: UUID
    competencias: list[str] = Field(min_length=1)
    orcamento: float = Field(ge=0)
    # Ausente num comando publicado antes da conferência de cobertura (T-241): o worker então
    # não a faz, e a execução segue como antes do campo existir.
    elementos_exigidos: list[ReferenciaDeElemento] | None = Field(default=None, min_length=1)

    @field_validator("elementos_exigidos")
    @classmethod
    def _sem_repeticao(cls, elementos: list[str] | None) -> list[str] | None:
        """O schema exige itens únicos: uma referência repetida não identifica outro elemento."""
        if elementos is not None and len(elementos) != len(set(elementos)):
            raise ValueError("elementos_exigidos repete uma referência")
        return elementos


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
