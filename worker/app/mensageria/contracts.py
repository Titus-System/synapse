"""DTOs das mensagens de RabbitMQ usadas pelo worker."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

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
    # Ausente quando o job não tem orçamento: a simulação é conferida como sempre e o sucesso
    # sai sem veredito e sem totais.orcamento (T-281). Só a ausência significa isso.
    orcamento: float | None = Field(default=None, ge=0)
    # Ausente quando a execução usa as vendas históricas. Com ela, o sandbox escala as vendas do
    # período até a meta e reapura o baseline sobre elas, e o worker confere esse baseline por
    # conta própria (T-270). Só a ausência significa vendas históricas.
    meta_venda: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    # Não muda a execução: é gravado no resultado e devolvido no evento, para a api distinguir a
    # simulação do job da execução candidata da busca da meta (T-273, T-274).
    proposito: Literal["simulacao", "busca_meta"] = "simulacao"
    # Ausente num comando publicado antes da conferência de cobertura (T-241): o worker então
    # não a faz, e a execução segue como antes do campo existir.
    elementos_exigidos: list[ReferenciaDeElemento] | None = Field(default=None, min_length=1)

    @field_validator("orcamento", "meta_venda", mode="before")
    @classmethod
    def _nulo_nao_e_ausencia(cls, valor: object, info: ValidationInfo) -> object:
        """O schema declara `orcamento` e `meta_venda` números, e `null` não é número. Lido como
        ausência, um produtor com defeito faria o worker pular em silêncio a verificação de
        orçamento, ou simular nas vendas históricas uma execução pedida na meta; o validador só
        roda quando o campo vem no corpo, então a ausência segue valendo."""
        if valor is None:
            raise ValueError(
                f"{info.field_name} presente não pode ser nulo; para não usá-lo, omita-o"
            )
        return valor

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
    # A meta da execução, ausente quando ela usou as vendas históricas (T-270).
    meta_venda: float | None = None
    # Ausente equivale a simulacao: o worker o publica só para a execução candidata da busca.
    proposito: Literal["simulacao", "busca_meta"] | None = None
