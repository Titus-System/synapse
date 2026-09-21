"""Carga das bases e do baseline embutidos na imagem do sandbox (T-033).

Lê os JSONL do dataset canônico e os entrega ao harness com tipos explícitos, na
forma que ``contracts/harness/README.md`` fixa em "Convenção de tipos das colunas".
Nenhuma tabela nasce de inferência de tipo: uma competência sem linha nenhuma
produziria ``float64`` onde o contrato manda ``int64``, e o código gerado, escrito
contra o contrato, erraria em silêncio.

Não abre rede, não recalcula o baseline e não executa código gerado. O baseline é
dado congelado (T-032), já na forma de ``apuracao_base``; este módulo valida e tipa a carga.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple, NoReturn

import pandas

# Este arquivo fica em <raiz>/app/sandbox/ tanto no repositório (worker/) quanto na
# imagem (/app), e os dados em <raiz>/sandbox/data/domrock nos dois: o mesmo cálculo
# serve aos dois lugares e os testes fora do container leem o dado real.
RAIZ_DADOS = Path(__file__).resolve().parents[2] / "sandbox" / "data" / "domrock"

CENTAVO = Decimal("0.01")

# As quatro chaves de ``bases``, sempre presentes (contrato T-034).
TABELAS = ("rh", "vendas", "comissoes", "eventos_rh")
# ``eventos_rh`` é a exceção do recorte: chega inteira, porque um evento de
# competência anterior (ex.: correção cadastral) ainda pode afetar um mês do período.
TABELAS_INTEIRAS = frozenset({"eventos_rh"})


class Tipo(StrEnum):
    TEXTO = "texto"
    TEXTO_OPCIONAL = "texto_opcional"
    INTEIRO = "inteiro"
    DECIMAL = "decimal"
    OBJETO_OPCIONAL = "objeto_opcional"


# Texto e objeto ficam em ``object``, como o pandas 2.x faz: o contrato trava a
# versão para o código gerado se comportar como foi escrito, e ``StringDtype`` muda
# ``fillna`` e comparação. Nulo permanece ``None``, nunca ``NaN`` nem ``"None"``.
DTYPE_POR_TIPO: Mapping[Tipo, str] = {
    Tipo.TEXTO: "object",
    Tipo.TEXTO_OPCIONAL: "object",
    Tipo.INTEIRO: "int64",
    Tipo.DECIMAL: "float64",
    Tipo.OBJETO_OPCIONAL: "object",
}

# Fonte única dos tipos por coluna. A ordem é a do schema.json. Um teste confere que
# este mapa cobre exatamente as colunas e os tipos que o schema declara: sem ele,
# duas fontes de verdade poderiam divergir em silêncio.
COLUNAS: Mapping[str, Mapping[str, Tipo]] = {
    "rh": {
        "competencia": Tipo.TEXTO,
        "data_ref": Tipo.TEXTO,
        "cod_marca": Tipo.INTEIRO,
        "descr_marca": Tipo.TEXTO,
        "cod_loja": Tipo.INTEIRO,
        "descr_loja": Tipo.TEXTO,
        "matricula": Tipo.TEXTO,
        "data_admiss": Tipo.TEXTO,
        "data_demiss": Tipo.TEXTO_OPCIONAL,
        "cod_cargo": Tipo.INTEIRO,
        "descr_cargo": Tipo.TEXTO,
    },
    "vendas": {
        "competencia": Tipo.TEXTO,
        "data_ref": Tipo.TEXTO,
        "data_venda": Tipo.TEXTO_OPCIONAL,
        "cod_marca": Tipo.INTEIRO,
        "descr_marca": Tipo.TEXTO,
        "cod_loja": Tipo.INTEIRO,
        "descr_loja": Tipo.TEXTO,
        "matricula": Tipo.TEXTO,
        "vlr_venda": Tipo.DECIMAL,
    },
    "comissoes": {
        "competencia": Tipo.TEXTO,
        "cod_marca": Tipo.INTEIRO,
        "descr_marca": Tipo.TEXTO,
        "cod_cargo": Tipo.INTEIRO,
        "descr_cargo": Tipo.TEXTO,
        "percentual_comissao": Tipo.DECIMAL,
    },
    "eventos_rh": {
        "id": Tipo.TEXTO,
        "tipo": Tipo.TEXTO,
        "matricula": Tipo.TEXTO,
        "competencia_origem": Tipo.TEXTO,
        "data_inicio": Tipo.TEXTO_OPCIONAL,
        "data_fim": Tipo.TEXTO_OPCIONAL,
        "detalhes": Tipo.OBJETO_OPCIONAL,
    },
    # A forma de ``apuracao_base`` no contrato é também o formato do baseline T-032 em disco.
    "apuracao_base": {
        "matricula": Tipo.TEXTO,
        "cod_loja": Tipo.INTEIRO,
        "cod_marca": Tipo.INTEIRO,
        "cod_cargo": Tipo.INTEIRO,
        "competencia": Tipo.TEXTO,
        "comissao": Tipo.DECIMAL,
    },
}


class CargaError(ValueError):
    """Dado embutido fora do que o contrato e o schema declaram."""


class CompetenciaNaoPublicadaError(CargaError):
    """Competência pedida que o dataset canônico não publica."""


class BaseInconsistenteError(CargaError):
    """O baseline congelado não bate com o RH ou com o manifesto."""


class Entrada(NamedTuple):
    bases: dict[str, pandas.DataFrame]
    apuracao_base: pandas.DataFrame
    # A mesma tabela em registros Python. É o que o harness entrega à agregação: o
    # DataFrame acima vai (em cópia) para a função gerada, e o que ela receber pode ser
    # alterado por ela; estes registros, não.
    registros_base: tuple[dict[str, object], ...]


def ler_jsonl(caminho: Path) -> list[dict[str, object]]:
    """Lê um JSONL de objetos. Cópia de ``scripts/build_baselines.ler_jsonl``: ``scripts/``
    não entra na imagem, e importá-lo puxaria as regras de competência."""
    registros: list[dict[str, object]] = []
    with caminho.open(encoding="utf-8") as arquivo:
        for numero, linha in enumerate(arquivo, start=1):
            if not linha.strip():
                continue
            valor = json.loads(linha, parse_constant=_recusar_constante)
            if not isinstance(valor, dict):
                raise CargaError(f"{caminho.name}, linha {numero}: esperado objeto")
            registros.append(valor)
    return registros


def _recusar_constante(constante: str) -> NoReturn:
    # json.loads aceita NaN e Infinity por padrão; nenhum deles é dado válido aqui.
    raise CargaError(f"valor não finito no dado embutido: {constante}")


def competencias_publicadas(*, raiz: Path = RAIZ_DADOS) -> tuple[str, ...]:
    esquema = json.loads((raiz / "schema.json").read_text(encoding="utf-8"))
    publicadas = esquema.get("published_competencias")
    if (
        not isinstance(publicadas, list)
        or not publicadas
        or not all(isinstance(competencia, str) for competencia in publicadas)
    ):
        raise CargaError("schema.json não declara published_competencias")
    return tuple(publicadas)


def carregar(competencias: Sequence[str], *, raiz: Path = RAIZ_DADOS) -> Entrada:
    """Carrega as bases e o baseline do período, tipados como o contrato manda."""
    periodo = _conferir_periodo(competencias, raiz)
    registros = {nome: ler_jsonl(raiz / f"{nome}.jsonl") for nome in TABELAS}

    recortados = {nome: _recortar(nome, registros[nome], periodo) for nome in TABELAS}
    bases = {nome: _tabela(nome, recortados[nome]) for nome in TABELAS}

    linhas_base = _linhas_apuracao_base(raiz, periodo, recortados["rh"])
    apuracao_base = _tabela("apuracao_base", list(enumerate(linhas_base, start=1)))
    return Entrada(bases, apuracao_base, tuple(linhas_base))


def _conferir_periodo(competencias: Sequence[str], raiz: Path) -> tuple[str, ...]:
    periodo = tuple(competencias)
    if not periodo:
        raise CargaError("competencias não pode ser vazia")
    if len(set(periodo)) != len(periodo):
        raise CargaError(f"competencias tem item repetido: {list(periodo)}")
    publicadas = competencias_publicadas(raiz=raiz)
    fora = [competencia for competencia in periodo if competencia not in publicadas]
    if fora:
        raise CompetenciaNaoPublicadaError(
            f"competência não publicada: {fora}; o dataset cobre {list(publicadas)}"
        )
    return periodo


def _recortar(
    nome: str, registros: Sequence[Mapping[str, object]], periodo: tuple[str, ...]
) -> list[tuple[int, Mapping[str, object]]]:
    """Recorta ao período, guardando o número da linha no arquivo para as mensagens."""
    numerados = list(enumerate(registros, start=1))
    if nome in TABELAS_INTEIRAS:
        return numerados
    return [
        (numero, registro)
        for numero, registro in numerados
        if registro.get("competencia") in periodo
    ]


def _tabela(nome: str, registros: Sequence[tuple[int, Mapping[str, object]]]) -> pandas.DataFrame:
    colunas = COLUNAS[nome]
    valores: dict[str, list[object]] = {coluna: [] for coluna in colunas}
    for numero, registro in registros:
        extras = registro.keys() - colunas.keys()
        if extras:
            raise CargaError(f"{nome}, linha {numero}: colunas fora do schema: {sorted(extras)}")
        for coluna, tipo in colunas.items():
            valores[coluna].append(_valor(nome, numero, registro, coluna, tipo))
    # Series com dtype explícito, nunca DataFrame(registros) nem read_json: os dois
    # inferem, e um período vazio perderia o dtype do contrato.
    series = {
        coluna: pandas.Series(valores[coluna], dtype=DTYPE_POR_TIPO[tipo])
        for coluna, tipo in colunas.items()
    }
    return pandas.DataFrame(series, columns=list(colunas))


def _valor(
    nome: str, numero: int, registro: Mapping[str, object], coluna: str, tipo: Tipo
) -> object:
    if coluna not in registro:
        raise CargaError(f"{nome}, linha {numero}: falta a coluna {coluna}")
    valor = registro[coluna]
    if tipo is Tipo.TEXTO and isinstance(valor, str):
        return valor
    if tipo is Tipo.TEXTO_OPCIONAL and (valor is None or isinstance(valor, str)):
        return valor
    if tipo is Tipo.INTEIRO and isinstance(valor, int) and not isinstance(valor, bool):
        return valor
    if (
        tipo is Tipo.DECIMAL
        and isinstance(valor, int | float)
        and not isinstance(valor, bool)
        and math.isfinite(valor)
    ):
        return float(valor)
    if tipo is Tipo.OBJETO_OPCIONAL and (valor is None or isinstance(valor, dict)):
        return valor
    # Só o tipo entra na mensagem: o valor seria linha de dataset num log.
    raise CargaError(
        f"{nome}, linha {numero}, coluna {coluna}: esperado {tipo.value}, "
        f"recebido {type(valor).__name__}"
    )


def _linhas_apuracao_base(
    raiz: Path,
    periodo: tuple[str, ...],
    rh: Sequence[tuple[int, Mapping[str, object]]],
) -> list[dict[str, object]]:
    """Lê os baselines T-032 já publicados na forma de ``apuracao_base``.

    Não há adaptação de nível, rename nem reconstrução de marca: o artefato congelado
    é o próprio contrato. A carga apenas valida competência, unicidade, dimensões contra
    o RH e a conciliação com o manifesto.
    """
    pessoas = _indexar_rh(rh)
    manifesto = json.loads((raiz / "baselines" / "manifesto.json").read_text(encoding="utf-8"))
    linhas: list[dict[str, object]] = []
    for competencia in periodo:
        esperado = manifesto["baselines"].get(competencia)
        if esperado is None:
            raise BaseInconsistenteError(f"manifesto.json não tem o baseline de {competencia}")
        do_mes = _linhas_do_mes(raiz / esperado["arquivo"], competencia, pessoas)
        _conferir_manifesto(competencia, do_mes, esperado)
        linhas.extend(do_mes)
    return linhas


def _indexar_rh(
    rh: Sequence[tuple[int, Mapping[str, object]]],
) -> dict[tuple[str, str], Mapping[str, object]]:
    pessoas: dict[tuple[str, str], Mapping[str, object]] = {}
    for numero, registro in rh:
        chave = (str(registro["competencia"]), str(registro["matricula"]))
        if chave in pessoas:
            raise BaseInconsistenteError(f"rh, linha {numero}: {chave[1]} repetida em {chave[0]}")
        pessoas[chave] = registro
    return pessoas


def _linhas_do_mes(
    caminho: Path, competencia: str, pessoas: Mapping[tuple[str, str], Mapping[str, object]]
) -> list[dict[str, object]]:
    linhas: list[dict[str, object]] = []
    vistas: set[str] = set()
    colunas = set(COLUNAS["apuracao_base"])
    for numero, linha in enumerate(ler_jsonl(caminho), start=1):
        origem = f"{caminho.name}, linha {numero}"
        extras = linha.keys() - colunas
        ausentes = colunas - linha.keys()
        if extras:
            raise BaseInconsistenteError(f"{origem}: colunas fora do contrato: {sorted(extras)}")
        if ausentes:
            raise BaseInconsistenteError(
                f"{origem}: faltam colunas do contrato: {sorted(ausentes)}"
            )

        matricula = _texto_da_base(linha, "matricula", origem)
        if linha.get("competencia") != competencia:
            raise BaseInconsistenteError(f"{origem}: competência diferente de {competencia}")
        if matricula in vistas:
            raise BaseInconsistenteError(f"{origem}: {matricula} repetida em {competencia}")
        vistas.add(matricula)

        cod_loja = _inteiro_da_base(linha, "cod_loja", origem)
        cod_marca = _inteiro_da_base(linha, "cod_marca", origem)
        cod_cargo = _inteiro_da_base(linha, "cod_cargo", origem)
        pessoa = pessoas.get((competencia, matricula))
        if pessoa is None:
            raise BaseInconsistenteError(f"{origem}: {matricula} não existe no rh de {competencia}")
        for campo, do_baseline in (
            ("cod_marca", cod_marca),
            ("cod_loja", cod_loja),
            ("cod_cargo", cod_cargo),
        ):
            if pessoa[campo] != do_baseline:
                raise BaseInconsistenteError(
                    f"{origem}: {campo} do baseline ({do_baseline}) difere do rh ({pessoa[campo]})"
                )
        linhas.append(dict(linha))
    return linhas


def _texto_da_base(linha: Mapping[str, object], campo: str, origem: str) -> str:
    valor = linha.get(campo)
    if not isinstance(valor, str) or not valor:
        raise BaseInconsistenteError(f"{origem}: {campo} deve ser texto não vazio")
    return valor


def _inteiro_da_base(linha: Mapping[str, object], campo: str, origem: str) -> int:
    valor = linha.get(campo)
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise BaseInconsistenteError(f"{origem}: {campo} deve ser inteiro")
    return valor


def _conferir_manifesto(
    competencia: str, linhas: Sequence[Mapping[str, object]], esperado: Mapping[str, object]
) -> None:
    """Fecha o circuito: um baseline trocado ou truncado não passa despercebido."""
    if len(linhas) != esperado["matriculas"]:
        raise BaseInconsistenteError(
            f"{competencia}: {len(linhas)} matrículas, "
            f"o manifesto registra {esperado['matriculas']}"
        )
    total = Decimal(0)
    for linha in linhas:
        comissao = linha["comissao"]
        if not isinstance(comissao, int | float) or isinstance(comissao, bool):
            raise BaseInconsistenteError(f"{competencia}: comissão não numérica no baseline")
        if not math.isfinite(comissao):
            raise BaseInconsistenteError(f"{competencia}: comissão não finita no baseline")
        total += Decimal(str(comissao))
    total = total.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    if total != Decimal(str(esperado["total"])).quantize(CENTAVO, rounding=ROUND_HALF_UP):
        raise BaseInconsistenteError(
            f"{competencia}: as matrículas somam {total}, o manifesto registra {esperado['total']}"
        )
