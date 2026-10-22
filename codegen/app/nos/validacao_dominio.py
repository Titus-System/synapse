"""Nó ``validacao_dominio``: verificação determinística de completude e coerência.

Roda sobre a representação da regra, sem chamar a LLM nem tocar as bases. Cada
conflito nomeia o elemento em conflito no vocabulário de
``comum.schema.json#/$defs/elemento_ref`` (``nucleo.<campo>`` ou ``elem.<n>``) e
em quê ele conflita; enquanto houver conflito, o avanço para a geração de código
fica bloqueado.
"""

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.extracao.vocabulario import carregar_vocabulario
from app.nos.codigos_conflito import CodigoConflito


@dataclass(frozen=True, slots=True)
class Conflito:
    elementos: tuple[str, ...]
    motivo: str
    codigo: CodigoConflito


@dataclass(frozen=True, slots=True)
class ResultadoValidacao:
    conflitos: tuple[Conflito, ...] = ()

    @property
    def liberado(self) -> bool:
        return not self.conflitos


def verificar(
    representacao: Mapping[str, object],
    parametros: Mapping[str, object] | None = None,
    *,
    competencias_publicadas: Collection[str] = (),
    sem_lastro: Collection[str] = (),
) -> ResultadoValidacao:
    """Verifica a regra e, com `parametros`, a completude para nova simulação.

    `competencias_publicadas` são os meses com dados: com `parametros`, uma competência fora
    delas é conflito, e por isso quem passa os parâmetros passa também a lista. `sem_lastro`
    são os parâmetros que a extração inicial descartou por falta de lastro no texto; só a
    versão nascida da extração os tem.
    """
    conflitos: list[Conflito] = []
    conflitos.extend(_completude_do_nucleo(representacao))
    conflitos.extend(_coerencia_do_percentual(representacao))
    conflitos.extend(_coerencia_das_taxas_por_cargo(representacao))
    conflitos.extend(_coerencia_da_vigencia(representacao))
    conflitos.extend(_coerencia_de_exclusoes(representacao))
    conflitos.extend(_conflitos_dos_elementos(representacao))
    if parametros is not None:
        conflitos.extend(_escopos_ausentes(representacao))
        conflitos.extend(_conflitos_dos_parametros(parametros, competencias_publicadas))
    conflitos.extend(_parametros_sem_lastro(sem_lastro))
    return ResultadoValidacao(tuple(conflitos))


# O `motivo` é texto do sistema, sem o valor que o usuário disse (T-280).
_SEM_LASTRO = {
    "orcamento": "orçamento citado sem valor reconhecido",
    "meta_venda": "meta de venda citada sem valor reconhecido",
    "competencias": "período da simulação citado sem meses reconhecidos",
}


def _conflitos_dos_parametros(
    parametros: Mapping[str, object], competencias_publicadas: Collection[str]
) -> list[Conflito]:
    conflitos: list[Conflito] = []
    orcamento = _numero(parametros.get("orcamento"))
    if orcamento is None:
        conflitos.append(
            Conflito(
                ("parametros.orcamento",),
                "orçamento não informado",
                CodigoConflito.ORCAMENTO_AUSENTE,
            )
        )
    elif orcamento < 0:
        conflitos.append(
            Conflito(
                ("parametros.orcamento",), "orçamento negativo", CodigoConflito.ORCAMENTO_NEGATIVO
            )
        )
    meta = _numero(parametros.get("meta_venda"))
    if meta is None:
        conflitos.append(
            Conflito(
                ("parametros.meta_venda",),
                "meta de vendas não informada",
                CodigoConflito.META_VENDA_AUSENTE,
            )
        )
    elif meta <= 0:
        # Sem vendas a escalar, a simulação sobre a meta não tem o que calcular.
        conflitos.append(
            Conflito(
                ("parametros.meta_venda",),
                "meta de venda zero ou negativa",
                CodigoConflito.META_VENDA_NAO_POSITIVA,
            )
        )
    competencias = parametros.get("competencias")
    if isinstance(competencias, list) and any(
        competencia not in competencias_publicadas for competencia in competencias
    ):
        # Sem dado nem baseline para o mês, a simulação dele não existe.
        conflitos.append(
            Conflito(
                ("parametros.competencias",),
                "competência sem dados publicados",
                CodigoConflito.COMPETENCIA_NAO_PUBLICADA,
            )
        )
    return conflitos


def _escopos_ausentes(representacao: Mapping[str, object]) -> list[Conflito]:
    nucleo = representacao.get("nucleo")
    if not isinstance(nucleo, Mapping):
        nucleo = {}
    return [
        Conflito(
            (f"nucleo.{campo}",),
            f"escopo de {campo} não informado; indique os destinatários ou declare todos",
            CodigoConflito.ESCOPO_AUSENTE,
        )
        for campo in ("loja", "marca", "cargo")
        if campo not in nucleo
    ]


def _parametros_sem_lastro(campos: Collection[str]) -> list[Conflito]:
    # Na ordem do contrato, e não na do chamador, para o resultado ser determinístico.
    return [
        Conflito((f"parametros.{campo}",), motivo, CodigoConflito.PARAMETRO_SEM_LASTRO)
        for campo, motivo in _SEM_LASTRO.items()
        if campo in campos
    ]


def _completude_do_nucleo(representacao: Mapping[str, object]) -> list[Conflito]:
    nucleo = representacao.get("nucleo")
    percentual = nucleo.get("percentual") if isinstance(nucleo, Mapping) else None
    taxas = nucleo.get("taxas_por_cargo") if isinstance(nucleo, Mapping) else None
    if percentual is None and not taxas:
        return [
            Conflito(
                ("nucleo.percentual",), "percentual ausente", CodigoConflito.PERCENTUAL_AUSENTE
            )
        ]
    return []


def _coerencia_das_taxas_por_cargo(representacao: Mapping[str, object]) -> list[Conflito]:
    nucleo = representacao.get("nucleo")
    if not isinstance(nucleo, Mapping):
        return []
    taxas = nucleo.get("taxas_por_cargo")
    if not isinstance(taxas, list):
        return []
    conflitos: list[Conflito] = []
    por_cargo: dict[str, Decimal] = {}
    cargos = nucleo.get("cargo")
    for taxa in taxas:
        if not isinstance(taxa, Mapping):
            continue
        cargo, percentual = taxa.get("cargo"), _numero(taxa.get("percentual"))
        if not isinstance(cargo, str) or percentual is None:
            continue
        codigo = None
        motivo = ""
        if percentual < 0:
            codigo, motivo = CodigoConflito.PERCENTUAL_NEGATIVO, "taxa por cargo negativa"
        elif cargo not in carregar_vocabulario()["cargo"]:
            codigo, motivo = CodigoConflito.TAXA_CARGO_DESCONHECIDO, "cargo da taxa não reconhecido"
        elif isinstance(cargos, list) and cargos and cargo not in cargos:
            codigo, motivo = CodigoConflito.TAXA_CARGO_FORA_ESCOPO, "taxa para cargo fora do núcleo"
        elif cargo in por_cargo and por_cargo[cargo] != percentual:
            codigo, motivo = (
                CodigoConflito.TAXA_CARGO_CONTRADITORIA,
                "taxas distintas para o mesmo cargo",
            )
        por_cargo[cargo] = percentual
        if codigo is not None:
            conflito = Conflito(("nucleo.taxas_por_cargo",), motivo, codigo)
            if conflito not in conflitos:
                conflitos.append(conflito)
    return conflitos


def _coerencia_do_percentual(representacao: Mapping[str, object]) -> list[Conflito]:
    nucleo = representacao.get("nucleo")
    if not isinstance(nucleo, Mapping):
        return []
    percentual = _numero(nucleo.get("percentual"))
    if percentual is not None and percentual < 0:
        return [
            Conflito(
                ("nucleo.percentual",),
                f"percentual negativo ({percentual})",
                CodigoConflito.PERCENTUAL_NEGATIVO,
            )
        ]
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
                    CodigoConflito.EXCLUSAO_REPETIDA,
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
        return [
            Conflito(
                ("nucleo.vigencia",),
                f"fim {fim} anterior ao início {inicio}",
                CodigoConflito.VIGENCIA_INVERTIDA,
            )
        ]
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
        return Conflito(
            (ref,),
            f"limite inferior {inferior} maior que o superior {superior}",
            CodigoConflito.FAIXA_INVERTIDA,
        )
    return None


def _janela_invertida(elemento: Mapping[str, object], ref: str) -> Conflito | None:
    inicio = _como_data(elemento.get("data_inicial"))
    fim = _como_data(elemento.get("data_final"))
    if inicio is not None and fim is not None and fim < inicio:
        return Conflito(
            (ref,),
            f"data final {fim} anterior à inicial {inicio}",
            CodigoConflito.JANELA_INVERTIDA,
        )
    return None


def _limiar_sem_escopo(elemento: Mapping[str, object], ref: str) -> Conflito | None:
    escopo = elemento.get("escopo_agregacao")
    if isinstance(escopo, str) and escopo:
        return None
    return Conflito(
        (ref,), "condição por limiar sem escopo de agregação", CodigoConflito.LIMIAR_SEM_ESCOPO
    )


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
