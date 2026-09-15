from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, ClassVar, Literal, Self
from uuid import UUID

import simplejson
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as ErroSchema
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator
from referencing import Registry, Resource

type Competencia = Annotated[str, Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]
type NoGrafo = Literal[
    "extracao_parametros",
    "validacao_dominio",
    "confirmacao",
    "geracao_codigo",
    "delegacao_worker",
    "interpretacao_resultado",
    "decisao",
    "explicacao",
]
type ElementoRef = Annotated[str, Field(pattern=r"^(nucleo\.[a-z_]+|elem\.[0-9]+)$")]
type Texto = Annotated[str, Field(min_length=1)]


def _numero_exato(valor: object) -> object:
    if isinstance(valor, float | bool | str):
        raise ValueError("Número deve ser Decimal ou inteiro")
    return valor


type Numero = Annotated[Decimal, BeforeValidator(_numero_exato), Field(allow_inf_nan=False)]


class ContratoError(ValueError):
    pass


@lru_cache
def validador(nome: str) -> Draft202012Validator:
    diretorio = Path(__file__).resolve().parents[2] / "contracts"
    esquemas = {
        arquivo.relative_to(diretorio).as_posix(): simplejson.loads(
            arquivo.read_text(encoding="utf-8"), use_decimal=True
        )
        for arquivo in diretorio.rglob("*.schema.json")
    }
    registro = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in esquemas.values()
    )
    return Draft202012Validator(
        esquemas[f"events/{nome}.schema.json"], registry=registro, format_checker=FormatChecker()
    )


def validar(nome: str, payload: object) -> None:
    try:
        validador(nome).validate(payload)
    except ErroSchema:
        raise ContratoError("Mensagem incompatível com o contrato") from None


def _escalar(valor: object) -> str:
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, datetime):
        return valor.isoformat().replace("+00:00", "Z")
    raise TypeError("Tipo não serializável no contrato")


class ModeloBase(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, allow_inf_nan=False)


class Mensagem(ModeloBase):
    nome: ClassVar[str]
    job_id: UUID

    def serializar(self) -> bytes:
        # Decimal precisa sair como número JSON, sem passar por float ou string.
        return simplejson.dumps(
            self.model_dump(mode="python", exclude_unset=True, warnings="error"),
            default=_escalar,
            use_decimal=True,
            allow_nan=False,
            ensure_ascii=False,
        ).encode("utf-8")

    @model_validator(mode="after")
    def conferir_contrato(self) -> Self:
        validar(self.nome, simplejson.loads(self.serializar(), use_decimal=True))
        return self


class RegraSubmetida(Mensagem):
    nome = "regra-submetida"
    origem: Literal["formulario", "voz", "reprocessamento"]
    competencias: list[Competencia] = Field(min_length=1)
    submissao_id: UUID | None = None
    regra_id: UUID | None = None


class ParametrosConfirmados(Mensagem):
    nome = "parametros-confirmados"
    regra_id: UUID


class SimulacaoConcluida(Mensagem):
    nome = "simulacao-concluida"
    resultado_id: UUID
    status: Literal["sucesso", "assercao_violada", "erro_codigo", "erro_infra"]
    veredito: Literal["viavel", "inviavel", "indeterminado"] | None = None
    total_baseline: Numero | None = None
    total_simulado: Numero | None = None
    diferenca_abs: Numero | None = None
    diferenca_pct: Numero | None = None


class ExecutarCodigo(Mensagem):
    nome = "executar-codigo"
    codigo_gerado_id: UUID
    competencias: list[Competencia] = Field(min_length=1)
    orcamento: Numero = Field(ge=0)


class EtapaAlterada(Mensagem):
    nome = "etapa-alterada"
    etapa: NoGrafo
    status: Texto


class Conclusao(ModeloBase):
    resumo: Texto
    fontes: list[Texto] | None = None
    elementos_extraidos: list[ElementoRef] | None = None
    no_dominio: bool | None = None
    editado_pelo_usuario: bool | None = None
    campos_corrigidos: list[ElementoRef] | None = None
    elementos_implementados: list[ElementoRef] | None = None
    diagnostico: str | None = None
    concentracao: list[str] | None = None
    encaminhamento: str | None = None


class NoConcluido(Mensagem):
    nome = "no-concluido"
    evento_id: UUID
    no: NoGrafo
    concluido_em: AwareDatetime
    conclusao: Conclusao
    regra_id: UUID | None = None
    simulacao_id: UUID | None = None
    prompt_id: UUID | None = None
    codigo_gerado_id: UUID | None = None
    explicacao_id: UUID | None = None


type Entrada = RegraSubmetida | ParametrosConfirmados | SimulacaoConcluida
type Saida = ExecutarCodigo | EtapaAlterada | NoConcluido
