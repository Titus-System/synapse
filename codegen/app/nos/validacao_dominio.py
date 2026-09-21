"""Nó ``validacao_dominio``: verificação determinística de completude e coerência.

Roda sobre a representação da regra, sem chamar a LLM nem tocar as bases. Cada
conflito nomeia o elemento em conflito no vocabulário de
``comum.schema.json#/$defs/elemento_ref`` (``nucleo.<campo>`` ou ``elem.<n>``) e
em quê ele conflita; enquanto houver conflito, o avanço para a geração de código
fica bloqueado.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Conflito:
    elementos: tuple[str, ...]
    motivo: str


@dataclass(frozen=True, slots=True)
class ResultadoValidacao:
    conflitos: tuple[Conflito, ...] = ()

    @property
    def liberado(self) -> bool:
        return not self.conflitos


def verificar(representacao: Mapping[str, object]) -> ResultadoValidacao:
    conflitos: list[Conflito] = []
    conflitos.extend(_completude_do_nucleo(representacao))
    conflitos.extend(_coerencia_do_percentual(representacao))
    conflitos.extend(_coerencia_da_vigencia(representacao))
    conflitos.extend(_coerencia_de_exclusoes(representacao))
    conflitos.extend(_conflitos_dos_elementos(representacao))
    return ResultadoValidacao(tuple(conflitos))


def _completude_do_nucleo(representacao: Mapping[str, object]) -> list[Conflito]:
    # Só o percentual é obrigatório: loja/marca/cargo/vigência ausentes valem como "todos".
    nucleo = representacao.get("nucleo")
    percentual = nucleo.get("percentual") if isinstance(nucleo, Mapping) else None
    if percentual is None:
        return [Conflito(("nucleo.percentual",), "percentual ausente")]
    return []


def _coerencia_do_percentual(representacao: Mapping[str, object]) -> list[Conflito]:
    nucleo = representacao.get("nucleo")
    if not isinstance(nucleo, Mapping):
        return []
    percentual = _numero(nucleo.get("percentual"))
    if percentual is not None and percentual < 0:
        return [Conflito(("nucleo.percentual",), f"percentual negativo ({percentual})")]
    return []


def _coerencia_de_exclusoes(representacao: Mapping[str, object]) -> list[Conflito]:
    nucleo = representacao.get("nucleo")
    especificacoes = representacao.get("especificacoes")
    if not isinstance(nucleo, Mapping) or not isinstance(especificacoes, list):
        return []
    conflitos: list[Conflito] = []
    for elemento in especificacoes:
        if not isinstance(elemento, Mapping) or elemento.get("construto") != "exclusao":
            continue
        ref = elemento.get("ref")
        dimensao = elemento.get("dimensao")
        valores = elemento.get("valores")
        if not (isinstance(ref, str) and isinstance(dimensao, str) and isinstance(valores, list)):
            continue
        incluidos = nucleo.get(dimensao)
        if not isinstance(incluidos, list):
            continue
        repetidos = [str(valor) for valor in valores if valor in incluidos]
        if repetidos:
            conflitos.append(
                Conflito(
                    (f"nucleo.{dimensao}", ref),
                    f"{dimensao} {', '.join(repetidos)} no núcleo e na exclusão",
                )
            )
    return conflitos


def _coerencia_da_vigencia(representacao: Mapping[str, object]) -> list[Conflito]:
    nucleo = representacao.get("nucleo")
    if not isinstance(nucleo, Mapping):
        return []
    vigencia = nucleo.get("vigencia")
    if not isinstance(vigencia, Mapping):
        return []
    inicio = vigencia.get("inicio")
    fim = vigencia.get("fim")
    if isinstance(inicio, str) and isinstance(fim, str) and fim < inicio:
        return [Conflito(("nucleo.vigencia",), f"fim {fim} anterior ao início {inicio}")]
    return []


def _conflitos_dos_elementos(representacao: Mapping[str, object]) -> list[Conflito]:
    especificacoes = representacao.get("especificacoes")
    if not isinstance(especificacoes, list):
        return []
    conflitos: list[Conflito] = []
    for elemento in especificacoes:
        if isinstance(elemento, Mapping):
            conflitos.extend(_conflitos_do_elemento(elemento))
    return conflitos


def _conflitos_do_elemento(elemento: Mapping[str, object]) -> list[Conflito]:
    ref = elemento.get("ref")
    construto = elemento.get("construto")
    if not isinstance(ref, str) or not isinstance(construto, str):
        return []
    verificacao = _VERIFICACOES.get(construto)
    if verificacao is None:
        return []
    conflito = verificacao(elemento, ref)
    return [conflito] if conflito is not None else []


def _faixa_invertida(elemento: Mapping[str, object], ref: str) -> Conflito | None:
    inferior = _numero(elemento.get("limite_inferior"))
    superior = _numero(elemento.get("limite_superior"))
    if inferior is not None and superior is not None and inferior > superior:
        return Conflito((ref,), f"limite inferior {inferior} maior que o superior {superior}")
    return None


def _janela_invertida(elemento: Mapping[str, object], ref: str) -> Conflito | None:
    inicio = _como_data(elemento.get("data_inicial"))
    fim = _como_data(elemento.get("data_final"))
    if inicio is not None and fim is not None and fim < inicio:
        return Conflito((ref,), f"data final {fim} anterior à inicial {inicio}")
    return None


def _limiar_sem_escopo(elemento: Mapping[str, object], ref: str) -> Conflito | None:
    escopo = elemento.get("escopo_agregacao")
    if isinstance(escopo, str) and escopo:
        return None
    return Conflito((ref,), "condição por limiar sem escopo de agregação")


def _numero(valor: object) -> Decimal | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, int):
        return Decimal(valor)
    if isinstance(valor, float):
        return Decimal(str(valor))
    return None


def _como_data(valor: object) -> date | None:
    # O estado carrega a data como date após o round-trip do LangGraph e como texto ISO
    # quando vem direto do schema; ambas as formas precisam ser comparáveis aqui.
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        try:
            return date.fromisoformat(valor)
        except ValueError:
            return None
    return None


_VERIFICACOES: dict[str, Callable[[Mapping[str, object], str], Conflito | None]] = {
    "faixa_valor": _faixa_invertida,
    "janela_datas": _janela_invertida,
    "condicao_limiar": _limiar_sem_escopo,
}
