"""Detalhamento vindo do container é dado não confiável (T-259)."""

from dataclasses import replace

import pytest

from app.execucao.coleta import classificar
from app.execucao.registro import linha_do_julgamento
from app.execucao.schema import carregar_contratos, validador
from app.execucao.veredito import Julgamento
from tests.app.execucao.envelopes import ORCAMENTO, PAYLOAD, envelope, saida


@pytest.mark.parametrize(
    "defeito",
    [
        "ausente",
        "nulo",
        "lista",
        "competencia_ausente",
        "competencia_extra",
        "matricula",
        "comissao",
        "campo_ausente",
        "contribuicao_zero",
        "elemento",
        "chave_hostil",
    ],
)
def test_detalhamento_malformado_e_resultado_fora_do_schema(defeito: str) -> None:
    dados = envelope()
    linha = dados["linhas"]["2025-11"]["MATRIC-1"]
    if defeito == "ausente":
        del dados["linhas"]
    elif defeito == "nulo":
        dados["linhas"] = None
    elif defeito == "lista":
        dados["linhas"] = []
    elif defeito == "competencia_ausente":
        del dados["linhas"]["2025-08"]
    elif defeito == "competencia_extra":
        dados["linhas"]["2025-09"] = {}
    elif defeito == "matricula":
        dados["linhas"]["2025-11"] = {"": linha}
    elif defeito == "comissao":
        linha["comissao_simulada"] = "CONTEUDO-PRIVADO"
    elif defeito == "campo_ausente":
        del linha["cod_loja"]
    elif defeito == "contribuicao_zero":
        linha["contribuicoes"]["elem.1"] = 0
    elif defeito == "elemento":
        linha["contribuicoes"] = {"CONTEUDO-PRIVADO": 10}
    else:
        dados["linhas"]["2025-11"]["CONTEUDO-PRIVADO"] = "CONTEUDO-PRIVADO"

    desfecho = classificar(saida(dados), PAYLOAD, ORCAMENTO)

    assert (desfecho.classe, desfecho.motivo) == ("erro_codigo", "resultado_fora_do_schema")
    assert desfecho.linhas is None and desfecho.resultado is None
    assert desfecho.problemas
    assert all(p["caminho"] == "$.linhas" for p in desfecho.problemas)
    assert "CONTEUDO-PRIVADO" not in repr(desfecho)


def test_coleta_e_registro_preservam_detalhamento_sem_recompor() -> None:
    dados = envelope()
    # A T-259 confere forma e competências. Valores e cobertura são da T-262.
    dados["linhas"]["2025-11"]["MATRIC-1"]["comissao_simulada"] = 999.99
    desfecho = classificar(saida(dados), PAYLOAD, ORCAMENTO)
    assert desfecho.classe == "sucesso"
    julgamento = Julgamento("sucesso", "ok", None, resultado=desfecho.resultado, desfecho=desfecho)

    linha = linha_do_julgamento(julgamento)

    assert linha.linhas is desfecho.linhas
    assert linha.linhas == dados["linhas"]
    assert "MATRIC-1" not in repr(linha)
    assert "linhas" not in linha.totais
    for status in ("assercao_violada", "erro_codigo", "erro_infra"):
        recusado = replace(julgamento, classe=status, motivo="baseline_divergente")
        assert linha_do_julgamento(recusado).linhas is None


def test_schema_do_detalhamento_e_carregado_na_subida() -> None:
    validador.cache_clear()
    carregar_contratos()
    antes = validador.cache_info()
    validador("resultado-linhas.schema.json")
    assert validador.cache_info().hits == antes.hits + 1
