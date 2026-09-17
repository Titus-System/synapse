"""Invariantes internas da apuração; sem I/O, baseline ou orçamento.

As referências são índices de linha (1-based) das tabelas recebidas, não IDs
inventados pela saída. Regras de competência podem fornecer direitos a bônus
como entrada da apuração; apenas uma etiqueta no resultado não prova origem.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import TypedDict

type Registro = Mapping[str, object]


class Desfecho(TypedDict):
    nome: str
    resultado: str
    detalhe: str | None


class ResultadoApuracao(TypedDict):
    status: str
    veredito: None
    competencia: str
    assercoes: list[Desfecho]
    total: float | None
    por_loja: dict[str, float] | None
    por_matricula: dict[str, float] | None


class AssercaoVioladaError(ValueError):
    """Falha terminal de cálculo, nunca inviabilidade orçamentária."""

    def __init__(self, resultado: ResultadoApuracao) -> None:
        self.resultado = resultado
        super().__init__(
            "; ".join(
                f"{item['nome']}: {item['detalhe']}"
                for item in resultado["assercoes"]
                if item["resultado"] == "violada"
            )
        )


class TabelaApurada(list[dict[str, object]]):
    """Preserva a interface de lista de T-030 e incorpora o desfecho."""

    def __init__(self, linhas: Sequence[dict[str, object]], resultado: ResultadoApuracao) -> None:
        super().__init__(linhas)
        self.resultado_apuracao = resultado


def numero_finito(valor: object) -> Decimal:
    if isinstance(valor, bool) or not isinstance(valor, int | float | str | Decimal):
        raise ValueError("valor não numérico")
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as erro:
        raise ValueError("valor não numérico") from erro
    if not numero.is_finite():
        raise ValueError("valor não finito")
    return numero


def _linha(tabela: Sequence[Registro], referencia: object) -> Registro | None:
    if type(referencia) is not int or not 1 <= referencia <= len(tabela):
        return None
    return tabela[referencia - 1]


def _lista(valor: object) -> list[object]:
    return valor if isinstance(valor, list) else []


def _demissao(rh: Registro, eventos: Sequence[Registro], competencia: str) -> str | None:
    valor = rh.get("data_demiss")
    for evento in sorted(
        eventos, key=lambda e: (str(e.get("competencia_origem")), str(e.get("id")))
    ):
        if evento.get("matricula") != rh.get("matricula"):
            continue
        if str(evento.get("competencia_origem")) > competencia:
            continue
        if evento.get("tipo") == "demissao":
            valor = evento.get("data_inicio")
        detalhes = evento.get("detalhes")
        if (
            evento.get("tipo") == "correcao_cadastral"
            and isinstance(detalhes, Mapping)
            and detalhes.get("campo") in {"Data_Demiss", "data_demiss"}
        ):
            valor = detalhes.get("valor_novo")
    return valor if isinstance(valor, str) else None


def _evento_remunerado(evento: Registro, matricula: object, competencia: str) -> bool:
    if evento.get("matricula") != matricula or evento.get("tipo") not in {
        "afastamento",
        "licenca_maternidade",
    }:
        return False
    fim = evento.get("data_fim")
    detalhes = evento.get("detalhes")
    if fim is None and isinstance(detalhes, Mapping):
        fim = detalhes.get("data_fim_estimada")
    try:
        inicio = date.fromisoformat(str(evento.get("data_inicio")))
        ultimo = date.fromisoformat(str(fim))
        mes = date.fromisoformat(f"{competencia}-01")
    except ValueError:
        return False
    fim_mes = mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])
    return max(inicio, mes) <= min(ultimo, inicio + timedelta(days=14), fim_mes)


def _origem_valida(
    linha: Registro,
    rh: Sequence[Registro],
    vendas: Sequence[Registro],
    eventos: Sequence[Registro],
    eventos_por_id: Mapping[str, Registro],
    direitos: Mapping[tuple[str, str], Registro],
    competencia: str,
) -> str | None:
    rastreio = linha.get("rastreabilidade")
    if not isinstance(rastreio, Mapping):
        return "rastreabilidade ausente"
    pessoa = _linha(rh, rastreio.get("linha_rh"))
    if pessoa is None or pessoa.get("matricula") != linha.get("matricula"):
        return "linha_rh não corresponde à matrícula"
    if pessoa.get("competencia") != competencia or pessoa.get("cod_cargo") != linha.get("cargo"):
        return "linha_rh não corresponde à competência/cargo"
    demissao = _demissao(pessoa, eventos, competencia)
    if demissao is not None and demissao[:7] < competencia:
        return "matrícula demitida antes da competência"
    if str(pessoa.get("data_admiss"))[:7] > competencia:
        return "matrícula admitida após a competência"

    tem_venda = False
    referencias = _lista(rastreio.get("linhas_vendas"))
    vistas: set[int] = set()
    for referencia in referencias:
        venda = _linha(vendas, referencia)
        if venda is None or venda.get("competencia") != competencia:
            return f"venda {referencia!r} inexistente ou de outra competência"
        if referencia in vistas:
            return f"referência de venda duplicada: {referencia}"
        vistas.add(int(str(referencia)))
        if linha.get("cargo") == 150:
            if venda.get("cod_loja") != pessoa.get("cod_loja"):
                return f"venda {referencia} não pertence à loja do gerente"
        elif venda.get("matricula") != linha.get("matricula"):
            return f"venda {referencia} não pertence à matrícula"
        data_venda = venda.get("data_venda")
        if data_venda is not None and str(data_venda)[:7] != competencia:
            return f"venda {referencia} fora da competência"
        if linha.get("cargo") != 150 and demissao and data_venda and str(data_venda) > demissao:
            return f"venda {referencia} posterior à demissão"
        try:
            tem_venda |= numero_finito(venda.get("vlr_venda")) > 0
        except ValueError:
            return f"venda {referencia} com valor inválido"

    tem_evento = False
    for identificador in _lista(rastreio.get("eventos_rh")):
        evento = eventos_por_id.get(str(identificador))
        if evento is None or evento.get("matricula") != linha.get("matricula"):
            return f"evento RH {identificador!r} inexistente ou de outra matrícula"
        tem_evento |= _evento_remunerado(evento, linha.get("matricula"), competencia)

    tem_bonus = False
    for identificador in _lista(rastreio.get("regras_competencia")):
        direito = direitos.get((str(identificador), str(linha.get("matricula"))))
        if direito is None or direito.get("competencia") != competencia:
            return f"regra da competência {identificador!r} sem origem de entrada correspondente"
        if direito.get("tipo") in {"bonus_final", "bonus_base"}:
            try:
                tem_bonus |= numero_finito(direito.get("valor")) > 0
            except ValueError:
                return f"regra da competência {identificador!r} com valor inválido"
    if not (tem_venda or tem_evento or tem_bonus):
        return "comissão positiva sem venda, evento remunerado ou bônus rastreável"
    return None


def finalizar_apuracao(
    linhas: Sequence[Registro],
    *,
    competencia: str,
    rh: Sequence[Registro],
    vendas: Sequence[Registro],
    eventos_rh: Sequence[Registro],
    por_loja: Mapping[str, object],
    origens_competencia: Sequence[Registro] = (),
) -> ResultadoApuracao:
    """Valida detalhes contra o acumulador de lojas produzido durante o cálculo.

    Deve ser chamada pelo executor *dentro* do container após a regra gerada.
    Não executa código, não lê arquivos e não emite veredito de orçamento.
    As três verificações são concluídas mesmo quando a primeira falha.
    """
    erros: list[list[str]] = [[], [], []]
    lojas: dict[str, Decimal] = defaultdict(Decimal)
    matriculas: dict[str, Decimal] = {}
    eventos = {str(e.get("id")): e for e in eventos_rh}
    direitos = {
        (str(e.get("id")), str(e.get("matricula"))): e
        for e in origens_competencia
        if e.get("competencia") == competencia
    }
    for indice, linha in enumerate(linhas, 1):
        matricula = str(linha.get("matricula", ""))
        ponto = (
            f"{competencia}, linha {indice}, matrícula {matricula}, loja {linha.get('cod_loja')}"
        )
        try:
            valor = numero_finito(linha.get("comissao"))
        except ValueError as erro:
            erros[0].append(f"{ponto}: {erro}")
            erros[2].append(f"{ponto}: comissão não somável")
            continue
        if valor < 0:
            erros[0].append(f"{ponto}: comissão {valor} negativa")
        if valor > 0:
            motivo = _origem_valida(linha, rh, vendas, eventos_rh, eventos, direitos, competencia)
            if motivo:
                erros[1].append(f"{ponto}: {motivo}")
        if not matricula or matricula in matriculas:
            erros[2].append(f"{ponto}: matrícula ausente ou duplicada")
        matriculas[matricula] = valor
        loja = linha.get("cod_loja")
        if type(loja) is not int:
            erros[2].append(f"{ponto}: cod_loja ausente ou inválido")
            continue
        rastreio = linha.get("rastreabilidade")
        pessoa = _linha(rh, rastreio.get("linha_rh")) if isinstance(rastreio, Mapping) else None
        if (
            pessoa is None
            or pessoa.get("cod_loja") != loja
            or pessoa.get("descr_loja") != linha.get("loja")
        ):
            erros[2].append(f"{ponto}: loja diverge da lotação do RH")
        lojas[str(loja)] += valor

    informado: dict[str, Decimal] = {}
    for loja, valor_loja in por_loja.items():
        try:
            informado[loja] = numero_finito(valor_loja)
        except ValueError as erro:
            erros[2].append(f"{competencia}, loja {loja}: {erro}")
    for loja in sorted(lojas.keys() | informado.keys()):
        if loja not in lojas or loja not in informado or lojas[loja] != informado[loja]:
            erros[2].append(
                f"{competencia}, loja {loja}: matrículas={lojas.get(loja)}, "
                f"acumulador={informado.get(loja)}"
            )
    total = sum(matriculas.values(), Decimal(0))
    if total != sum(informado.values(), Decimal(0)):
        erros[2].append(f"{competencia}: total por matrícula {total} diverge do total por loja")
    nomes = ("sem_comissao_negativa", "sem_comissao_sem_venda", "soma_loja_igual_soma_matricula")
    assercoes: list[Desfecho] = [
        {
            "nome": nome,
            "resultado": "violada" if falhas else "ok",
            "detalhe": "; ".join(falhas) if falhas else None,
        }
        for nome, falhas in zip(nomes, erros, strict=True)
    ]
    falhou = any(erros)
    return {
        "status": "assercao_violada" if falhou else "sucesso",
        "veredito": None,
        "competencia": competencia,
        "assercoes": assercoes,
        "total": None if falhou else float(total),
        "por_loja": None if falhou else {k: float(v) for k, v in sorted(informado.items())},
        "por_matricula": None if falhou else {k: float(v) for k, v in sorted(matriculas.items())},
    }
