from typing import Annotated
from uuid import UUID

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel, ConfigDict, Field

from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import Competencia, Orcamento, Origem, Veredito


class EstadoGrafo(BaseModel):
    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, revalidate_instances="always"
    )

    job_id: UUID
    origem: Origem
    competencias: Annotated[list[Competencia], Field(min_length=1)]
    orcamento: Orcamento | None = None
    representacao_regra: RepresentacaoRegra | None = None
    codigo_gerado: str | None = None
    referencia_resultado: UUID | None = None
    veredito_recebido: Veredito | None = None
    historico_sugestoes: list[RepresentacaoRegra] = Field(default_factory=list)


def _serializador() -> JsonPlusSerializer:
    # Somente valores e tipos da biblioteca padrão, sem reconstruir classes da aplicação.
    return JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=[])


def serializar_estado(estado: EstadoGrafo) -> tuple[str, bytes]:
    valores = EstadoGrafo.model_validate(estado.model_dump(mode="python"))
    return _serializador().dumps_typed(valores.model_dump(mode="python"))


def desserializar_estado(dados: tuple[str, bytes]) -> EstadoGrafo:
    if dados[0] != "msgpack":
        raise ValueError("O estado deve estar no formato msgpack do LangGraph")
    return EstadoGrafo.model_validate(_serializador().loads_typed(dados))
