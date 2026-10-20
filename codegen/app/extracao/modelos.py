from dataclasses import dataclass
from typing import Any, Literal

from app.falhas import FalhaDoJobError
from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import ValorRegra

type MotivoRebaixamento = Literal[
    "construto_nao_habilitado",
    "campo_obrigatorio_ausente",
    "valor_sem_lastro",
    "codigo_fora_do_vocabulario",
    "termo_ambiguo",
    "periodo_nao_resolvido",
]


class FalhaExtracaoError(FalhaDoJobError):
    etapa = "extracao_parametros"


class ElementoRebaixadoError(ValueError):
    """O conversor de um construto recusa o rascunho e diz por quê, sem reter o conteúdo."""

    def __init__(
        self, motivo: MotivoRebaixamento, campos: dict[str, ValorRegra] | None = None
    ) -> None:
        super().__init__(motivo)
        self.motivo = motivo
        self.campos = campos


@dataclass(frozen=True, slots=True)
class Rebaixamento:
    ref: str
    motivo: MotivoRebaixamento
    construto_pretendido: str | None = None

    def para_contrato(self) -> dict[str, str]:
        resultado = {"ref": self.ref, "motivo": self.motivo}
        if self.construto_pretendido is not None:
            resultado["construto_pretendido"] = self.construto_pretendido
        return resultado


@dataclass(frozen=True, slots=True, repr=False)
class ChamadaExtracao:
    prompt: str
    resposta: str
    modelo: dict[str, Any]
    consumo_tokens: dict[str, int] | None


@dataclass(frozen=True, slots=True, repr=False)
class ResultadoExtracao:
    representacao: RepresentacaoRegra
    rebaixamentos: list[Rebaixamento]
    parametros: dict[str, ValorRegra]
    chamada: ChamadaExtracao
