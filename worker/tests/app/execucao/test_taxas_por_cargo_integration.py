from decimal import Decimal

import pytest

from app.execucao.bases import carregar_bases
from app.sandbox.escalonamento import escalar_vendas, fator_de_escala, reapurar_baseline
from scripts.casos_geracao import DIRETORIO_CASOS
from tests.app.execucao.test_execucao_na_meta_integration import executar_na_meta, meta_por_fator

pytestmark = pytest.mark.docker


@pytest.mark.parametrize("fator", ["1", "1.2"])
def test_cada_cargo_recebe_sua_taxa_e_os_demais_preservam_baseline_na_meta(
    imagem: str, fator: str
) -> None:
    competencias = ["2025-08", "2025-11"]
    meta = meta_por_fator(competencias, fator)
    fonte = (DIRETORIO_CASOS / "taxas-por-cargo" / "referencia.py").read_text(encoding="utf-8")
    _, julgamento = executar_na_meta(
        fonte, imagem, competencias, meta, elementos_exigidos=["nucleo.taxas_por_cargo"]
    )

    assert (julgamento.classe, julgamento.motivo) == ("sucesso", "ok")
    assert julgamento.desfecho is not None and julgamento.desfecho.linhas is not None
    linhas = julgamento.desfecho.linhas
    bases = carregar_bases()
    vendas = escalar_vendas(
        [v for v in bases.vendas if v["competencia"] in competencias],
        fator_de_escala(meta, bases.vendas_historicas(competencias)),
    )
    baseline = reapurar_baseline(
        bases.rh, vendas, bases.comissoes, bases.eventos_rh, bases.regras, competencias
    )
    quadro = {(b["competencia"], b["matricula"]) for b in baseline}
    verificados = {"100": 0, "150": 0, "baseline": 0}
    for original in baseline:
        competencia, matricula = str(original["competencia"]), str(original["matricula"])
        linha = linhas[competencia][matricula]
        esperado = Decimal(str(original["comissao"]))
        cargo = str(original["cod_cargo"])
        if str(original["cod_marca"]) == "10" and cargo in ("100", "150"):
            vendas_alvo = [
                v
                for v in vendas
                if v["competencia"] == competencia
                and (
                    v["matricula"] == matricula
                    if cargo == "100"
                    else v["cod_loja"] == original["cod_loja"]
                    and (competencia, v["matricula"]) in quadro
                )
            ]
            taxa = Decimal("0.03") if cargo == "100" else Decimal("0.05")
            esperado = sum((Decimal(str(v["vlr_venda"])) for v in vendas_alvo), Decimal(0)) * taxa
            verificados[cargo] += 1
        else:
            verificados["baseline"] += 1
            assert linha["comissao_simulada"] == original["comissao"]
            assert linha["contribuicoes"] == {}
        assert abs(Decimal(str(linha["comissao_simulada"])) - esperado) <= Decimal("0.01")
        assert linha["comissao_baseline"] == original["comissao"]
    assert all(quantidade > 0 for quantidade in verificados.values())
