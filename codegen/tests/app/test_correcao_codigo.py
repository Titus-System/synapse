import pytest

from app.correcao_codigo import (
    CAUSAS_DE_CORRECAO,
    LIMITE_DE_CODIGOS_POR_VERSAO,
    FalhaDaExecucao,
    corrige,
)


@pytest.mark.parametrize("status", ["erro_codigo", "assercao_violada"])
def test_falha_do_codigo_e_corrigida_ate_o_penultimo_codigo_da_versao(status: str) -> None:
    assert [corrige(status, posicao) for posicao in range(1, LIMITE_DE_CODIGOS_POR_VERSAO + 1)] == [
        True,
        True,
        False,
    ]


@pytest.mark.parametrize("status", ["sucesso", "erro_infra", None])
def test_outro_desfecho_nunca_e_corrigido(status: str | None) -> None:
    assert not corrige(status, 1)


def test_causa_vem_do_diagnostico_e_assercao_violada_tem_a_propria() -> None:
    assert FalhaDaExecucao("erro_codigo", {"causa": "cobertura_incompleta"}).causa() == (
        "cobertura_incompleta"
    )
    assert FalhaDaExecucao("assercao_violada").causa() == "assercao_violada"


@pytest.mark.parametrize("diagnostico", [None, {}, {"causa": "nova_causa"}, {"causa": 3}])
def test_causa_fora_do_conjunto_fechado_e_desconhecida(diagnostico: dict | None) -> None:
    """A causa é rótulo de métrica: um valor novo do worker não pode abrir uma série."""
    causa = FalhaDaExecucao("erro_codigo", diagnostico).causa()

    assert causa == "desconhecida"
    assert causa in CAUSAS_DE_CORRECAO


def test_falha_para_o_prompt_leva_so_o_que_o_worker_registrou() -> None:
    falha = FalhaDaExecucao(
        "erro_codigo",
        {
            "causa": "cobertura_incompleta",
            "elementos_ausentes": ["nucleo.taxas_por_cargo"],
            "problemas": [],
        },
    )

    assert falha.para_prompt() == {
        "status": "erro_codigo",
        "causa": "cobertura_incompleta",
        "elementos_ausentes": ["nucleo.taxas_por_cargo"],
    }


def test_assercoes_violadas_vao_ao_prompt_com_nome_e_detalhe() -> None:
    falha = FalhaDaExecucao(
        "assercao_violada",
        assercoes_violadas=[
            {"nome": "sem_comissao_negativa", "detalhe": "valor não finito", "resultado": "violada"}
        ],
    )

    assert falha.para_prompt() == {
        "status": "assercao_violada",
        "causa": "assercao_violada",
        "assercoes_violadas": [{"nome": "sem_comissao_negativa", "detalhe": "valor não finito"}],
    }


def test_linhas_fora_do_escopo_vao_ao_prompt_como_o_worker_as_gravou() -> None:
    linhas = {
        "total": 111,
        "exemplos": [
            {
                "competencia": "2025-08",
                "matricula": "MATRIC-371",
                "cod_loja": "33",
                "cod_marca": "10",
                "cod_cargo": "100",
                "diferenca": 350.0,
            }
        ],
    }
    falha = FalhaDaExecucao(
        "erro_codigo", {"causa": "fora_do_escopo", "linhas_fora_do_escopo": linhas}
    )

    assert falha.para_prompt() == {
        "status": "erro_codigo",
        "causa": "fora_do_escopo",
        "linhas_fora_do_escopo": linhas,
    }
