"""As vendas escaladas até a meta e o baseline reapurado sobre elas (T-270).

O oráculo é o dado real: com fator 1 a reapuração tem de reproduzir os baselines congelados linha a
linha, e com outro fator a proporção entre as vendas tem de sobreviver à escala. O módulo roda dos
dois lados (imagem do sandbox e processo do worker), e é a mesma conta que os dois fazem.
"""

import copy
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from functools import cache

import pytest

from app.sandbox.carga import RAIZ_DADOS, ler_jsonl
from app.sandbox.escalonamento import (
    MetaVendaError,
    escalar_vendas,
    fator_de_escala,
    reapurar_baseline,
    total_de_vendas,
)
from app.sandbox.regras_base import RegraBaseError

COMPETENCIAS = ("2025-08", "2025-09", "2025-10", "2025-11", "2025-12")


@cache
def base(nome: str) -> tuple[dict[str, object], ...]:
    return tuple(ler_jsonl(RAIZ_DADOS / nome))


def vendas_de(competencias: Sequence[str]) -> list[dict[str, object]]:
    return [venda for venda in base("vendas.jsonl") if venda["competencia"] in competencias]


def reapurar(
    vendas: Sequence[Mapping[str, object]], competencias: Sequence[str]
) -> list[dict[str, object]]:
    return reapurar_baseline(
        base("rh.jsonl"),
        vendas,
        base("comissoes.jsonl"),
        base("eventos_rh.jsonl"),
        base("regras_competencia.jsonl"),
        competencias,
    )


def congelado(competencia: str) -> list[dict[str, object]]:
    return ler_jsonl(RAIZ_DADOS / "baselines" / f"baseline-{competencia}.jsonl")


# ---- o total histórico e o fator ----


def test_o_total_historico_e_a_soma_das_vendas_em_centavos() -> None:
    """O mesmo valor do exemplo do contrato (resultado-totais-meta-venda.json)."""
    assert total_de_vendas(vendas_de(["2025-08", "2025-11"])) == Decimal("23583194.87")


def test_meta_igual_ao_total_historico_escala_por_exatamente_um() -> None:
    total = total_de_vendas(vendas_de(["2025-11"]))

    assert fator_de_escala(float(total), total) == 1


def test_periodo_sem_vendas_nao_tem_fator() -> None:
    with pytest.raises(MetaVendaError):
        fator_de_escala(1000.0, Decimal(0))


# ---- a escala ----


def test_toda_venda_e_multiplicada_pelo_mesmo_fator_e_nada_mais_muda() -> None:
    vendas = vendas_de(["2025-11"])
    fator = Decimal("1.1")

    escaladas = escalar_vendas(vendas, fator)

    assert len(escaladas) == len(vendas)
    for original, escalada in zip(vendas, escaladas, strict=True):
        assert escalada["vlr_venda"] == float(Decimal(str(original["vlr_venda"])) * fator)
        assert {**escalada, "vlr_venda": original["vlr_venda"]} == original


def test_a_escala_nao_altera_as_vendas_recebidas() -> None:
    vendas = vendas_de(["2025-11"])
    antes = copy.deepcopy(vendas)

    escalar_vendas(vendas, Decimal("1.3"))

    assert vendas == antes


def _cargo_de() -> Callable[[Mapping[str, object]], object]:
    cargos = {(p["competencia"], p["matricula"]): p["cod_cargo"] for p in base("rh.jsonl")}
    return lambda venda: cargos.get((venda["competencia"], venda["matricula"]))


@pytest.mark.parametrize(
    "dimensao",
    [
        lambda venda: venda["cod_loja"],
        lambda venda: venda["cod_marca"],
        lambda venda: venda["matricula"],
        lambda venda: venda["competencia"],
        _cargo_de(),
    ],
    ids=["loja", "marca", "pessoa", "competencia", "cargo"],
)
def test_a_proporcao_entre_os_grupos_se_mantem(
    dimensao: Callable[[Mapping[str, object]], object],
) -> None:
    """Cada grupo cresce pelo mesmo fator, então a participação de cada um no total não muda. A
    tolerância é a do float que guarda cada venda escalada, muito abaixo de um centavo."""
    vendas = vendas_de(COMPETENCIAS)
    fator = Decimal("1.37")
    escaladas = escalar_vendas(vendas, fator)

    antes: dict[object, Decimal] = defaultdict(Decimal)
    depois: dict[object, Decimal] = defaultdict(Decimal)
    for original, escalada in zip(vendas, escaladas, strict=True):
        antes[dimensao(original)] += Decimal(str(original["vlr_venda"]))
        depois[dimensao(escalada)] += Decimal(str(escalada["vlr_venda"]))

    assert len(antes) > 1
    for grupo, valor in antes.items():
        assert depois[grupo] == pytest.approx(valor * fator, rel=Decimal("1e-12"), abs=1e-6)


def test_venda_escalada_que_nao_cabe_num_float_e_recusada() -> None:
    with pytest.raises(MetaVendaError):
        escalar_vendas([{"vlr_venda": 1e300}], Decimal("1e10"))


# ---- a reapuração ----


def test_com_fator_um_a_reapuracao_reproduz_os_baselines_congelados_linha_a_linha() -> None:
    """A mesma função e as mesmas entradas de build_baselines: sobre as vendas históricas, o
    baseline reapurado é o congelado, nas cinco competências publicadas."""
    vendas = vendas_de(COMPETENCIAS)
    total = total_de_vendas(vendas)

    linhas = reapurar(escalar_vendas(vendas, fator_de_escala(float(total), total)), COMPETENCIAS)

    assert linhas == [linha for c in COMPETENCIAS for linha in congelado(c)]


def test_na_meta_a_reapuracao_nao_e_o_baseline_proporcional() -> None:
    """A apuração não é linear nas vendas (piso de afastamento, arredondamento por linha): é por
    isso que a escala vale para a entrada, e não para os totais depois da execução."""
    vendas = vendas_de(["2025-11"])

    linhas = reapurar(escalar_vendas(vendas, Decimal("1.1")), ["2025-11"])

    total = sum((Decimal(str(linha["comissao"])) for linha in linhas), Decimal(0))
    assert total == Decimal("558870.26")
    assert total != Decimal("508382.32") * Decimal("1.1")
    assert [linha["matricula"] for linha in linhas] == [
        linha["matricula"] for linha in congelado("2025-11")
    ]


# ---- a marca de cada linha (T-270) ----

# Uma política mínima, neutra (bônus zero, sem filtro): só para satisfazer a exigência de
# apurar_vigente de ao menos uma política publicada na competência.
POLITICA_NULA = [{"id": "T-TESTE", "competencia": "2025-08", "tipo": "bonus_final", "valor": 0}]


def test_cod_marca_e_a_unica_da_rastreabilidade() -> None:
    """O caso comum: uma venda, uma marca, igual ao rh."""
    rh = [_rh_sintetico("MATRIC-1", cod_marca=10)]
    vendas = [_venda_sintetica("MATRIC-1", 1000.0, cod_marca=10)]
    taxas = [_taxa_sintetica(cod_marca=10)]

    (linha,) = reapurar_baseline(rh, vendas, taxas, [], POLITICA_NULA, ["2025-08"])

    assert linha["cod_marca"] == 10


def test_matricula_com_vendas_em_duas_marcas_nao_tem_uma_cod_marca() -> None:
    """Sem a marca única, ``apuracao_base`` não teria onde pôr a coluna: o congelamento do
    baseline (``build_baselines._linhas_apuracao_base``) recusa o mesmo jeito, e nunca ocorreu
    nas competências já congeladas. A reapuração na meta tem de recusar igual, e não escolher
    uma marca em silêncio."""
    rh = [_rh_sintetico("MATRIC-1", cod_marca=10)]
    vendas = [
        _venda_sintetica("MATRIC-1", 1000.0, cod_marca=10),
        _venda_sintetica("MATRIC-1", 500.0, cod_marca=20),
    ]
    taxas = [_taxa_sintetica(cod_marca=10), _taxa_sintetica(cod_marca=20)]

    with pytest.raises(RegraBaseError, match="esperada exatamente uma cod_marca"):
        reapurar_baseline(rh, vendas, taxas, [], POLITICA_NULA, ["2025-08"])


def _rh_sintetico(matricula: str, *, cod_marca: int, cod_cargo: int = 100) -> dict[str, object]:
    return {
        "competencia": "2025-08",
        "data_ref": "2025-08-01",
        "cod_marca": cod_marca,
        "descr_marca": "MARCA",
        "cod_loja": 1,
        "descr_loja": "LOJA-1",
        "matricula": matricula,
        "data_admiss": "2020-01-01",
        "data_demiss": None,
        "cod_cargo": cod_cargo,
        "descr_cargo": "VENDEDOR",
    }


def _venda_sintetica(matricula: str, valor: float, *, cod_marca: int) -> dict[str, object]:
    return {
        "competencia": "2025-08",
        "data_ref": "2025-08-01",
        "data_venda": None,
        "cod_marca": cod_marca,
        "descr_marca": "MARCA",
        "cod_loja": 1,
        "descr_loja": "LOJA-1",
        "matricula": matricula,
        "vlr_venda": valor,
    }


def _taxa_sintetica(*, cod_marca: int, cod_cargo: int = 100) -> dict[str, object]:
    return {
        "competencia": "2025-08",
        "cod_marca": cod_marca,
        "descr_marca": "MARCA",
        "cod_cargo": cod_cargo,
        "descr_cargo": "VENDEDOR",
        "percentual_comissao": 0.01,
    }
