from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.representacao_regra import RepresentacaoRegra


class ModeloContrato(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class OrigemJob(StrEnum):
    FORMULARIO = "formulario"
    VOZ = "voz"
    REPROCESSAMENTO = "reprocessamento"
    TEXTO = "texto"


class StatusSimulacao(StrEnum):
    SUCESSO = "sucesso"
    ASSERCAO_VIOLADA = "assercao_violada"
    ERRO_CODIGO = "erro_codigo"
    ERRO_INFRA = "erro_infra"


class StatusTerminal(StrEnum):
    """Os estados em que o job não volta a processar: o vocabulário de `job-encerrado`."""

    LIBERADO = "liberado"
    CANCELADO = "cancelado"
    ARQUIVADO = "arquivado"
    ERRO = "erro"


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
    "sugestao_adaptacao",
    "explicacao",
]

TextoNaoVazio = Annotated[str, Field(min_length=1)]
ReferenciaDeElemento = Annotated[
    str,
    Field(pattern=r"^(nucleo\.[a-z_]+|elem\.[0-9]+)$"),
]
ReferenciaDeParametro = Annotated[
    str,
    Field(pattern=r"^parametros\.(orcamento|meta_venda|competencias)$"),
]


class ConclusaoDaTrilha(ModeloContrato):
    resumo: TextoNaoVazio
    fontes: list[TextoNaoVazio] | None = None
    elementos_extraidos: list[ReferenciaDeElemento] | None = None
    no_dominio: bool | None = None
    editado_pelo_usuario: bool | None = None
    campos_corrigidos: list[ReferenciaDeElemento] | None = None
    elementos_implementados: list[ReferenciaDeElemento] | None = None
    diagnostico: str | None = None
    concentracao: list[str] | None = None
    encaminhamento: str | None = None


class RegraSubmetida(ModeloContrato):
    job_id: UUID
    origem: OrigemJob
    competencias: list[str] = Field(min_length=1)
    submissao_id: UUID | None = None
    regra_id: UUID | None = None
    # Sem limite inferior, como no contrato: o orçamento negativo e a meta zero ou negativa
    # chegam ao grafo como foram ditos, para a validação de domínio apontá-los (T-280).
    orcamento: Decimal | None = None
    meta_venda: Decimal | None = None


class RegraExtraida(ModeloContrato):
    job_id: UUID
    submissao_id: UUID
    extracao_id: UUID


class ParametrosConfirmados(ModeloContrato):
    job_id: UUID
    regra_id: UUID
    competencias: list[str] | None = Field(default=None, min_length=1)
    # Sem limite inferior pelo mesmo motivo de `RegraSubmetida`.
    orcamento: Decimal | None = None
    meta_venda: Decimal | None = None


class CorrecaoSubmetida(ModeloContrato):
    job_id: UUID
    regra_origem_id: UUID
    submissao_id: UUID
    competencias: list[str] | None = Field(default=None, min_length=1)
    # Sem limite inferior, como no contrato: são os parâmetros atuais do job como foram ditos.
    orcamento: Decimal | None = None
    meta_venda: Decimal | None = None


class SimulacaoConcluida(ModeloContrato):
    job_id: UUID
    resultado_id: UUID
    status: StatusSimulacao
    veredito: Veredito | None = None
    meta_venda: Decimal | None = Field(default=None, gt=0)
    proposito: Literal["simulacao", "busca_meta"] | None = None
    total_baseline: Decimal | None = None
    total_simulado: Decimal | None = None
    diferenca_abs: Decimal | None = None
    diferenca_pct: Decimal | None = None


class JobEncerrado(ModeloContrato):
    evento_id: UUID
    job_id: UUID
    status: StatusTerminal
    encerrado_em: datetime


class SugestaoAdaptacaoProposta(ModeloContrato):
    job_id: UUID
    regra_origem_id: UUID
    resultado_id: UUID
    representacao: RepresentacaoRegra
    tentativa: int | None = Field(default=None, ge=1, le=3)


class ParametrosSimulacao(ModeloContrato):
    orcamento: Decimal | None = None
    meta_venda: Decimal | None = None
    competencias: list[str] | None = Field(default=None, min_length=1)


class CorrecaoProposta(ModeloContrato):
    job_id: UUID
    regra_origem_id: UUID
    submissao_id: UUID
    representacao: RepresentacaoRegra
    parametros: ParametrosSimulacao | None = None


class VigenciaDoAlcance(ModeloContrato):
    inicio: str
    fim: str


class ExcluidosDoAlcance(ModeloContrato):
    loja: list[str] | None = Field(default=None, min_length=1)
    marca: list[str] | None = Field(default=None, min_length=1)
    cargo: list[str] | None = Field(default=None, min_length=1)


class AlcanceDaExecucao(ModeloContrato):
    """As linhas a que a regra dá efeito; cada campo ausente não restringe a dimensão."""

    vigencia: VigenciaDoAlcance | None = None
    loja: list[str] | None = Field(default=None, min_length=1)
    marca: list[str] | None = Field(default=None, min_length=1)
    cargo: list[str] | None = Field(default=None, min_length=1)
    excluidos: ExcluidosDoAlcance | None = None


class ExecutarCodigo(ModeloContrato):
    job_id: UUID
    codigo_gerado_id: UUID
    competencias: list[str] = Field(min_length=1)
    orcamento: Decimal | None = Field(default=None, ge=0)
    meta_venda: Decimal | None = Field(default=None, gt=0)
    proposito: Literal["simulacao", "busca_meta"] | None = None
    elementos_exigidos: list[ReferenciaDeElemento] | None = Field(default=None, min_length=1)
    alcance: AlcanceDaExecucao | None = None


class ConflitoDaRodada(ModeloContrato):
    elementos: list[ReferenciaDeElemento | ReferenciaDeParametro] = Field(min_length=1)
    motivo: TextoNaoVazio


class EtapaAlterada(ModeloContrato):
    job_id: UUID
    etapa: NoGrafo
    status: str = Field(min_length=1)
    causa: Literal["provedor_indisponivel"] | None = None
    regra_id: UUID | None = None
    submissao_id: UUID | None = None
    conflitos: list[ConflitoDaRodada] | None = Field(default=None, min_length=1)


class NoConcluido(ModeloContrato):
    evento_id: UUID
    job_id: UUID
    no: NoGrafo
    concluido_em: datetime
    conclusao: ConclusaoDaTrilha
    regra_id: UUID | None = None
    simulacao_id: UUID | None = None
    prompt_id: UUID | None = None
    codigo_gerado_id: UUID | None = None
    explicacao_id: UUID | None = None


class SemSolucaoMeta(ModeloContrato):
    motivo: Literal["nao_monotonica", "intervalo_esgotado", "falha_execucao"]


class MetaVendaSugerida(ModeloContrato):
    job_id: UUID
    regra_id: UUID
    resultado_id: UUID | None = None
    meta_venda: Decimal | None = Field(default=None, gt=0)
    sem_solucao: SemSolucaoMeta | None = None
