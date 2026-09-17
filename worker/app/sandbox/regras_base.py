"""Regras base determinísticas de comissionamento da Dom Rock.

O módulo trabalha somente com registros do dataset canônico. Nenhuma leitura de XLSX
acontece aqui; a preparação dos arquivos de origem pertence ao script de T-026.
"""

from __future__ import annotations

import calendar
import warnings
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Protocol, cast

from app.sandbox.assercoes import (
    AssercaoVioladaError,
    ResultadoApuracao,
    TabelaApurada,
    finalizar_apuracao,
)

type Registro = Mapping[str, object]
type LinhaSaida = dict[str, object]
type TabelaSaida = list[LinhaSaida] | DataFrameLike

CENTAVO = Decimal("0.01")
PISO_AFASTAMENTO = Decimal("3500.00")
CARGO_GERENTE = 150
TIPOS_AFASTAMENTO = frozenset({"afastamento", "licenca_maternidade"})
TIPOS_CORRECAO = frozenset({"correcao_cadastral", "demissao"})


class DataFrameLike(Protocol):
    """Parte mínima da interface de DataFrame necessária para a função pública."""

    def to_dict(self, orient: str = "dict") -> object:
        """Converte a tabela em registros."""


class RegraBaseError(ValueError):
    """Indica dado incompatível com as regras base ou com o dataset canônico."""


class RegraCompetenciaForaDoEscopoError(RegraBaseError):
    """Indica tentativa de misturar regra da competência com a apuração base."""


class RuidoDadosWarning(UserWarning):
    """Sinaliza linha descartada por não possuir vínculo com o RH canônico."""


def apurar(
    rh: Sequence[Registro] | DataFrameLike,
    vendas: Sequence[Registro] | DataFrameLike,
    comissionamento: Sequence[Registro] | DataFrameLike,
    eventos_rh: Sequence[Registro] | DataFrameLike,
    competencia: str,
    regra: object | None = None,
) -> TabelaSaida:
    """Calcula a apuração base de uma competência.

    A função aceita listas de registros e objetos compatíveis com ``DataFrame.to_dict``.
    Quando ``rh`` é um DataFrame-like, a saída é reconstruída usando a mesma classe;
    com listas, retorna uma lista de dicionários.

    ``regra`` fica reservado ao fluxo de simulação. Regras específicas de competência
    não pertencem ao baseline e, por isso, não são aceitas nesta função.
    """
    if regra is not None:
        raise RegraCompetenciaForaDoEscopoError(
            "regras específicas da competência não fazem parte da apuração base"
        )

    inicio_mes, fim_mes = _limites_competencia(competencia)
    dias_mes = fim_mes.day

    linhas_rh = _extrair_linhas(rh, "rh")
    linhas_vendas = _extrair_linhas(vendas, "vendas")
    linhas_comissoes = _extrair_linhas(comissionamento, "comissionamento")
    linhas_eventos = _extrair_linhas(eventos_rh, "eventos_rh")

    eventos_por_matricula = _eventos_por_matricula(linhas_eventos)
    rh_efetivo = _preparar_rh(
        linhas_rh,
        eventos_por_matricula,
        competencia,
        inicio_mes,
        fim_mes,
    )
    taxas = _taxas_comissao(linhas_comissoes, competencia)
    vendas_validas, vendas_orfas = _filtrar_vendas(
        linhas_vendas,
        rh_efetivo,
        competencia,
        inicio_mes,
        fim_mes,
    )
    _avisar_vendas_orfas(vendas_orfas, competencia)

    vendas_por_matricula_marca: dict[tuple[str, int], Decimal] = defaultdict(Decimal)
    linhas_venda_por_matricula: dict[str, list[int]] = defaultdict(list)
    linhas_venda_por_loja: dict[int, list[int]] = defaultdict(list)
    vendas_por_loja: dict[int, Decimal] = defaultdict(Decimal)
    marcas_por_loja: dict[int, set[int]] = defaultdict(set)

    for numero_linha, venda in vendas_validas:
        matricula = _texto(venda, "matricula", "vendas")
        cod_marca = _inteiro(venda, "cod_marca", "vendas")
        cod_loja = _inteiro(venda, "cod_loja", "vendas")
        valor = _decimal(venda, "vlr_venda", "vendas")
        vendas_por_matricula_marca[(matricula, cod_marca)] += valor
        linhas_venda_por_matricula[matricula].append(numero_linha)
        linhas_venda_por_loja[cod_loja].append(numero_linha)
        vendas_por_loja[cod_loja] += valor
        marcas_por_loja[cod_loja].add(cod_marca)

    resultado: list[LinhaSaida] = []
    totais_por_loja: dict[str, Decimal] = defaultdict(Decimal)
    for matricula in sorted(rh_efetivo):
        registro_rh = rh_efetivo[matricula]
        if not registro_rh.elegivel:
            continue

        cargo = _inteiro(registro_rh.dados, "cod_cargo", "rh")
        loja = _inteiro(registro_rh.dados, "cod_loja", "rh")
        marca_rh = _inteiro(registro_rh.dados, "cod_marca", "rh")

        componentes = _componentes_base(
            matricula=matricula,
            cargo=cargo,
            loja=loja,
            marca_rh=marca_rh,
            vendas_por_matricula_marca=vendas_por_matricula_marca,
            vendas_por_loja=vendas_por_loja,
            marcas_por_loja=marcas_por_loja,
            taxas=taxas,
        )
        base_original = sum((item.base for item in componentes), Decimal(0))
        comissao_original = sum((item.comissao for item in componentes), Decimal(0))

        regras_aplicadas = ["5a", "5b" if cargo == CARGO_GERENTE else "5a"]
        fatores: dict[str, float] = {}
        base_calculo = base_original
        comissao = comissao_original

        fator_vinculo, regras_vinculo = _fator_vinculo(
            registro_rh.data_admiss,
            registro_rh.data_demiss,
            competencia,
            dias_mes,
        )
        if fator_vinculo != Decimal(1):
            base_calculo *= fator_vinculo
            comissao *= fator_vinculo
            fatores["vinculo"] = float(fator_vinculo)
            regras_aplicadas.extend(regras_vinculo)

        eventos = eventos_por_matricula.get(matricula, ())
        dias_ferias = _dias_eventos_no_mes(eventos, {"ferias"}, inicio_mes, fim_mes)
        if dias_ferias:
            fator_ferias = Decimal(dias_mes - len(dias_ferias)) / Decimal(dias_mes)
            base_calculo *= fator_ferias
            comissao *= fator_ferias
            fatores["ferias"] = float(fator_ferias)
            regras_aplicadas.append("5g")

        afastamento = _calcular_afastamento(eventos, inicio_mes, fim_mes)
        if afastamento.dias_total:
            regras_aplicadas.append("5e" if afastamento.duracao_maxima_evento <= 15 else "5f")
            dias_trabalhados = dias_mes - afastamento.dias_total

            if dias_trabalhados == 0:
                base_calculo = Decimal(0)
                comissao = Decimal(0)
            elif afastamento.dias_remunerados:
                fator_afastamento = Decimal(
                    dias_trabalhados + afastamento.dias_remunerados
                ) / Decimal(dias_trabalhados)
                base_calculo *= fator_afastamento
                comissao *= fator_afastamento
                fatores["afastamento"] = float(fator_afastamento)

            if afastamento.dias_remunerados:
                comissao = max(comissao, PISO_AFASTAMENTO)

        rastreabilidade = {
            "linha_rh": registro_rh.numero_linha,
            "linhas_vendas": list(
                linhas_venda_por_loja.get(loja, [])
                if cargo == CARGO_GERENTE
                else linhas_venda_por_matricula.get(matricula, [])
            ),
            "eventos_rh": [
                _texto(evento.dados, "id", "eventos_rh")
                for evento in eventos
                if _evento_relevante_na_competencia(evento.dados, inicio_mes, fim_mes, competencia)
            ],
            "chaves_comissao": [
                {
                    "cod_marca": item.cod_marca,
                    "cod_cargo": cargo,
                    "percentual_comissao": float(item.taxa),
                }
                for item in componentes
            ],
            "regras_aplicadas": list(dict.fromkeys(regras_aplicadas)),
            "base_original": _moeda(base_original),
            "fatores": fatores,
            "afastamento": {
                "dias_total": afastamento.dias_total,
                "dias_remunerados": afastamento.dias_remunerados,
                "piso_aplicado": bool(
                    afastamento.dias_remunerados and comissao == PISO_AFASTAMENTO
                ),
            },
        }
        comissao_final = _moeda(comissao)
        totais_por_loja[str(loja)] += Decimal(str(comissao_final))
        resultado.append(
            {
                "matricula": matricula,
                "cod_loja": loja,
                "loja": _texto(registro_rh.dados, "descr_loja", "rh"),
                "cargo": cargo,
                "base_calculo": _moeda(base_calculo),
                "comissao": comissao_final,
                "rastreabilidade": rastreabilidade,
            }
        )

    desfecho = finalizar_apuracao(
        resultado,
        competencia=competencia,
        rh=[linha.dados for linha in linhas_rh],
        vendas=[linha.dados for linha in linhas_vendas],
        eventos_rh=[linha.dados for linha in linhas_eventos],
        por_loja=totais_por_loja,
    )
    if desfecho["status"] != "sucesso":
        raise AssercaoVioladaError(desfecho)
    return _recriar_tabela(rh, resultado, desfecho)


class _LinhaComNumero:
    def __init__(self, numero_linha: int, dados: dict[str, object]) -> None:
        self.numero_linha = numero_linha
        self.dados = dados


class _RhEfetivo(_LinhaComNumero):
    def __init__(
        self,
        numero_linha: int,
        dados: dict[str, object],
        data_admiss: date,
        data_demiss: date | None,
        elegivel: bool,
    ) -> None:
        super().__init__(numero_linha, dados)
        self.data_admiss = data_admiss
        self.data_demiss = data_demiss
        self.elegivel = elegivel


class _ComponenteBase:
    def __init__(self, cod_marca: int, base: Decimal, taxa: Decimal) -> None:
        self.cod_marca = cod_marca
        self.base = base
        self.taxa = taxa
        self.comissao = base * taxa


class _AfastamentoMes:
    def __init__(self, dias_total: int, dias_remunerados: int, duracao_maxima_evento: int) -> None:
        self.dias_total = dias_total
        self.dias_remunerados = dias_remunerados
        self.duracao_maxima_evento = duracao_maxima_evento


def _extrair_linhas(
    tabela: Sequence[Registro] | DataFrameLike,
    nome: str,
) -> list[_LinhaComNumero]:
    if hasattr(tabela, "to_dict"):
        conversor = cast(DataFrameLike, tabela).to_dict
        valor = conversor(orient="records")
        if not isinstance(valor, list):
            raise RegraBaseError(f"{nome} não retornou registros no formato esperado")
        registros = valor
    else:
        registros = list(tabela)

    linhas: list[_LinhaComNumero] = []
    for numero, registro in enumerate(registros, start=1):
        if not isinstance(registro, Mapping):
            raise RegraBaseError(f"{nome}: linha {numero} não é um objeto")
        linhas.append(_LinhaComNumero(numero, dict(registro)))
    return linhas


def _recriar_tabela(
    modelo: Sequence[Registro] | DataFrameLike,
    linhas: list[LinhaSaida],
    resultado: ResultadoApuracao,
) -> TabelaSaida:
    if not hasattr(modelo, "to_dict"):
        return TabelaApurada(linhas, resultado)

    construtor = cast(Callable[[list[LinhaSaida]], DataFrameLike], type(modelo))
    tabela = construtor(linhas)
    atributos = getattr(tabela, "attrs", None)
    if isinstance(atributos, dict):
        atributos["resultado_apuracao"] = resultado
    else:
        tabela.resultado_apuracao = resultado  # type: ignore[attr-defined]
    return tabela


def _preparar_rh(
    linhas_rh: list[_LinhaComNumero],
    eventos_por_matricula: Mapping[str, Sequence[_LinhaComNumero]],
    competencia: str,
    inicio_mes: date,
    fim_mes: date,
) -> dict[str, _RhEfetivo]:
    resultado: dict[str, _RhEfetivo] = {}
    for linha in linhas_rh:
        dados = linha.dados.copy()
        if _texto(dados, "competencia", "rh") != competencia:
            continue

        matricula = _texto(dados, "matricula", "rh")
        if matricula in resultado:
            raise RegraBaseError(f"rh: matrícula duplicada na competência: {matricula}")

        correcoes = [
            evento
            for evento in eventos_por_matricula.get(matricula, ())
            if _texto(evento.dados, "tipo", "eventos_rh") in TIPOS_CORRECAO
            and _texto(evento.dados, "competencia_origem", "eventos_rh") <= competencia
        ]
        for evento in sorted(
            correcoes,
            key=lambda item: (
                _texto(item.dados, "competencia_origem", "eventos_rh"),
                _texto(item.dados, "id", "eventos_rh"),
            ),
        ):
            _aplicar_correcao(dados, evento.dados)

        data_admiss = _data(dados.get("data_admiss"), "rh.data_admiss")
        data_demiss = _data_opcional(dados.get("data_demiss"), "rh.data_demiss")
        elegivel = data_admiss <= fim_mes and (data_demiss is None or data_demiss >= inicio_mes)
        resultado[matricula] = _RhEfetivo(
            linha.numero_linha,
            dados,
            data_admiss,
            data_demiss,
            elegivel,
        )
    return resultado


def _aplicar_correcao(dados_rh: dict[str, object], evento: Registro) -> None:
    tipo = _texto(evento, "tipo", "eventos_rh")
    if tipo == "demissao":
        dados_rh["data_demiss"] = _texto(evento, "data_inicio", "eventos_rh")
        return

    detalhes = evento.get("detalhes")
    if not isinstance(detalhes, Mapping):
        raise RegraBaseError("correcao_cadastral sem bloco detalhes")

    campo = detalhes.get("campo")
    valor_novo = detalhes.get("valor_novo")
    campos = {
        "Data_Demiss": "data_demiss",
        "data_demiss": "data_demiss",
        "Data_Admiss": "data_admiss",
        "data_admiss": "data_admiss",
    }
    if not isinstance(campo, str) or campo not in campos:
        raise RegraBaseError(f"correcao_cadastral com campo não suportado: {campo!r}")
    if valor_novo is not None and not isinstance(valor_novo, str):
        raise RegraBaseError("correcao_cadastral: valor_novo deve ser data ISO ou null")
    dados_rh[campos[campo]] = valor_novo


def _taxas_comissao(
    linhas: list[_LinhaComNumero],
    competencia: str,
) -> dict[tuple[int, int], Decimal]:
    resultado: dict[tuple[int, int], Decimal] = {}
    for linha in linhas:
        if _texto(linha.dados, "competencia", "comissionamento") != competencia:
            continue
        chave = (
            _inteiro(linha.dados, "cod_marca", "comissionamento"),
            _inteiro(linha.dados, "cod_cargo", "comissionamento"),
        )
        if chave in resultado:
            raise RegraBaseError(f"comissionamento duplicado para marca/cargo {chave}")
        resultado[chave] = _decimal(linha.dados, "percentual_comissao", "comissionamento")
    return resultado


def _filtrar_vendas(
    linhas: list[_LinhaComNumero],
    rh_efetivo: Mapping[str, _RhEfetivo],
    competencia: str,
    inicio_mes: date,
    fim_mes: date,
) -> tuple[list[tuple[int, dict[str, object]]], list[_LinhaComNumero]]:
    validas: list[tuple[int, dict[str, object]]] = []
    orfas: list[_LinhaComNumero] = []
    for linha in linhas:
        if _texto(linha.dados, "competencia", "vendas") != competencia:
            continue
        matricula = _texto(linha.dados, "matricula", "vendas")
        funcionario = rh_efetivo.get(matricula)
        if funcionario is None:
            orfas.append(linha)
            continue
        if not funcionario.elegivel:
            continue

        data_venda = _data_opcional(linha.dados.get("data_venda"), "vendas.data_venda")
        if data_venda is not None and not (inicio_mes <= data_venda <= fim_mes):
            raise RegraBaseError(
                f"vendas: data_venda {data_venda.isoformat()} fora da competência {competencia}"
            )
        if (
            funcionario.data_demiss is not None
            and data_venda is not None
            and data_venda > funcionario.data_demiss
        ):
            continue
        validas.append((linha.numero_linha, linha.dados))
    return validas, orfas


def _avisar_vendas_orfas(linhas: Sequence[_LinhaComNumero], competencia: str) -> None:
    if not linhas:
        return
    matriculas = sorted({_texto(linha.dados, "matricula", "vendas") for linha in linhas})
    warnings.warn(
        RuidoDadosWarning(
            f"{len(linhas)} venda(s) da competência {competencia} foram excluídas por não "
            f"terem RH correspondente: {', '.join(matriculas)}"
        ),
        stacklevel=3,
    )


def _componentes_base(
    *,
    matricula: str,
    cargo: int,
    loja: int,
    marca_rh: int,
    vendas_por_matricula_marca: Mapping[tuple[str, int], Decimal],
    vendas_por_loja: Mapping[int, Decimal],
    marcas_por_loja: Mapping[int, set[int]],
    taxas: Mapping[tuple[int, int], Decimal],
) -> list[_ComponenteBase]:
    if cargo == CARGO_GERENTE:
        marcas_loja = marcas_por_loja.get(loja, set())
        if len(marcas_loja) > 1:
            raise RegraBaseError(f"loja {loja} possui mais de uma marca na mesma competência")
        taxa = _taxa_obrigatoria(taxas, marca_rh, cargo)
        return [_ComponenteBase(marca_rh, vendas_por_loja.get(loja, Decimal(0)), taxa)]

    componentes: list[_ComponenteBase] = []
    for (matricula_venda, cod_marca), valor in sorted(vendas_por_matricula_marca.items()):
        if matricula_venda != matricula:
            continue
        taxa = _taxa_obrigatoria(taxas, cod_marca, cargo)
        componentes.append(_ComponenteBase(cod_marca, valor, taxa))
    if not componentes:
        taxa = _taxa_obrigatoria(taxas, marca_rh, cargo)
        componentes.append(_ComponenteBase(marca_rh, Decimal(0), taxa))
    return componentes


def _taxa_obrigatoria(
    taxas: Mapping[tuple[int, int], Decimal],
    cod_marca: int,
    cod_cargo: int,
) -> Decimal:
    try:
        return taxas[(cod_marca, cod_cargo)]
    except KeyError as erro:
        raise RegraBaseError(
            f"percentual de comissão ausente para marca {cod_marca} e cargo {cod_cargo}"
        ) from erro


def _eventos_por_matricula(
    linhas: Sequence[_LinhaComNumero],
) -> dict[str, tuple[_LinhaComNumero, ...]]:
    agrupados: dict[str, list[_LinhaComNumero]] = defaultdict(list)
    for linha in linhas:
        matricula = _texto(linha.dados, "matricula", "eventos_rh")
        agrupados[matricula].append(linha)
    return {
        matricula: tuple(
            sorted(
                eventos,
                key=lambda item: (
                    _texto(item.dados, "competencia_origem", "eventos_rh"),
                    _texto(item.dados, "id", "eventos_rh"),
                ),
            )
        )
        for matricula, eventos in agrupados.items()
    }


def _dias_eventos_no_mes(
    eventos: Sequence[_LinhaComNumero],
    tipos: set[str],
    inicio_mes: date,
    fim_mes: date,
) -> set[date]:
    dias: set[date] = set()
    for evento in eventos:
        if _texto(evento.dados, "tipo", "eventos_rh") not in tipos:
            continue
        inicio, fim = _periodo_evento(evento.dados)
        dias.update(_dias_intersecao(inicio, fim, inicio_mes, fim_mes))
    return dias


def _calcular_afastamento(
    eventos: Sequence[_LinhaComNumero],
    inicio_mes: date,
    fim_mes: date,
) -> _AfastamentoMes:
    dias_total: set[date] = set()
    dias_remunerados: set[date] = set()
    duracao_maxima = 0

    for evento in eventos:
        if _texto(evento.dados, "tipo", "eventos_rh") not in TIPOS_AFASTAMENTO:
            continue
        inicio, fim = _periodo_evento(evento.dados)
        duracao = (fim - inicio).days + 1
        duracao_maxima = max(duracao_maxima, duracao)
        dias_total.update(_dias_intersecao(inicio, fim, inicio_mes, fim_mes))

        fim_remunerado = fim if duracao <= 15 else min(fim, inicio + timedelta(days=14))
        dias_remunerados.update(_dias_intersecao(inicio, fim_remunerado, inicio_mes, fim_mes))

    return _AfastamentoMes(len(dias_total), len(dias_remunerados), duracao_maxima)


def _periodo_evento(evento: Registro) -> tuple[date, date]:
    tipo = _texto(evento, "tipo", "eventos_rh")
    inicio = _data(evento.get("data_inicio"), "eventos_rh.data_inicio")
    fim = _data_opcional(evento.get("data_fim"), "eventos_rh.data_fim")

    if fim is None and tipo == "licenca_maternidade":
        detalhes = evento.get("detalhes")
        if isinstance(detalhes, Mapping):
            fim = _data_opcional(
                detalhes.get("data_fim_estimada"),
                "eventos_rh.detalhes.data_fim_estimada",
            )
    if fim is None:
        raise RegraBaseError(f"evento {tipo} sem data_fim utilizável")
    if fim < inicio:
        raise RegraBaseError(f"evento {tipo} com data_fim anterior à data_inicio")
    return inicio, fim


def _dias_intersecao(inicio: date, fim: date, limite_inicio: date, limite_fim: date) -> set[date]:
    primeiro = max(inicio, limite_inicio)
    ultimo = min(fim, limite_fim)
    if primeiro > ultimo:
        return set()
    return {primeiro + timedelta(days=offset) for offset in range((ultimo - primeiro).days + 1)}


def _evento_relevante_na_competencia(
    evento: Registro,
    inicio_mes: date,
    fim_mes: date,
    competencia: str,
) -> bool:
    tipo = _texto(evento, "tipo", "eventos_rh")
    if tipo in TIPOS_CORRECAO:
        return _texto(evento, "competencia_origem", "eventos_rh") <= competencia
    inicio, fim = _periodo_evento(evento)
    return max(inicio, inicio_mes) <= min(fim, fim_mes)


def _fator_vinculo(
    data_admiss: date,
    data_demiss: date | None,
    competencia: str,
    dias_mes: int,
) -> tuple[Decimal, list[str]]:
    admissao_no_mes = data_admiss.strftime("%Y-%m") == competencia
    demissao_no_mes = data_demiss is not None and data_demiss.strftime("%Y-%m") == competencia

    if admissao_no_mes and demissao_no_mes:
        if data_demiss is None:
            raise RegraBaseError("data de demissão ausente na competência")
        dias_trabalhados = data_demiss.day - data_admiss.day
        if dias_trabalhados < 0:
            raise RegraBaseError("data de demissão anterior à data de admissão na competência")
        return Decimal(dias_trabalhados) / Decimal(dias_mes), ["5c", "5d"]
    if admissao_no_mes:
        return Decimal(dias_mes - data_admiss.day) / Decimal(dias_mes), ["5c"]
    if demissao_no_mes:
        if data_demiss is None:
            raise RegraBaseError("data de demissão ausente na competência")
        return Decimal(data_demiss.day) / Decimal(dias_mes), ["5d"]
    return Decimal(1), []


def _limites_competencia(competencia: str) -> tuple[date, date]:
    try:
        ano_texto, mes_texto = competencia.split("-", maxsplit=1)
        ano = int(ano_texto)
        mes = int(mes_texto)
        if competencia != f"{ano:04d}-{mes:02d}":
            raise ValueError
        ultimo_dia = calendar.monthrange(ano, mes)[1]
    except (ValueError, IndexError) as erro:
        raise RegraBaseError(f"competência inválida: {competencia!r}; use YYYY-MM") from erro
    return date(ano, mes, 1), date(ano, mes, ultimo_dia)


def _texto(registro: Registro, campo: str, origem: str) -> str:
    valor = registro.get(campo)
    if not isinstance(valor, str) or not valor:
        raise RegraBaseError(f"{origem}.{campo} deve ser texto não vazio")
    return valor


def _inteiro(registro: Registro, campo: str, origem: str) -> int:
    valor = registro.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise RegraBaseError(f"{origem}.{campo} deve ser inteiro")
    return valor


def _decimal(registro: Registro, campo: str, origem: str) -> Decimal:
    valor = registro.get(campo)
    if isinstance(valor, bool) or not isinstance(valor, int | float | str | Decimal):
        raise RegraBaseError(f"{origem}.{campo} deve ser numérico")
    try:
        return Decimal(str(valor))
    except InvalidOperation as erro:
        raise RegraBaseError(f"{origem}.{campo} possui número inválido") from erro


def _data(valor: object, campo: str) -> date:
    if not isinstance(valor, str):
        raise RegraBaseError(f"{campo} deve ser data ISO")
    try:
        return date.fromisoformat(valor)
    except ValueError as erro:
        raise RegraBaseError(f"{campo} deve usar YYYY-MM-DD") from erro


def _data_opcional(valor: object, campo: str) -> date | None:
    if valor is None:
        return None
    return _data(valor, campo)


def _moeda(valor: Decimal) -> float:
    return float(valor.quantize(CENTAVO, rounding=ROUND_HALF_UP))
