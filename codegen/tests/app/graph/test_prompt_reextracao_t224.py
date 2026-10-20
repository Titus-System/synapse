"""Os textos históricos são dados, nunca instruções ou fonte de lastro novo."""

import json
from decimal import Decimal

from app.graph.prompts.reextraction import montar_prompt_reextracao
from app.repositorio.rodadas_correcao import CorrecaoAnterior
from app.representacao_regra import RepresentacaoRegra

REGRA = RepresentacaoRegra.model_validate(
    {"nucleo": {"percentual": Decimal("0.02")}, "especificacoes": []}
)


def _prompt(historico: list[CorrecaoAnterior]) -> dict[str, object]:
    return json.loads(
        montar_prompt_reextracao(REGRA, {}, [], "TEXTO_ATUAL_PRIVADO", [], historico=historico)
    )


def test_primeira_correcao_tem_apenas_o_texto_atual() -> None:
    corpo = _prompt([])

    assert corpo["dados_nao_confiaveis_da_correcao"] == {"texto": "TEXTO_ATUAL_PRIVADO"}


def test_terceira_correcao_tem_conflitos_e_textos_em_ordem_no_compartimento_correto() -> None:
    historico = [
        CorrecaoAnterior([{"elementos": ["elem.1"], "motivo": "MOTIVO_1"}], "ANTERIOR_1"),
        CorrecaoAnterior([{"elementos": ["elem.2"], "motivo": "MOTIVO_2"}], "ANTERIOR_2"),
    ]

    corpo = _prompt(historico)

    assert corpo["dados_nao_confiaveis_da_correcao"] == {
        "texto": "TEXTO_ATUAL_PRIVADO",
        "historico": [
            {"conflitos": historico[0].conflitos, "texto": "ANTERIOR_1"},
            {"conflitos": historico[1].conflitos, "texto": "ANTERIOR_2"},
        ],
    }
    for nome in ("instrucoes_fixas_do_sistema", "dados_do_sistema"):
        assert "ANTERIOR_" not in json.dumps(corpo[nome])
        assert "MOTIVO_" not in json.dumps(corpo[nome])
        assert "TEXTO_ATUAL_PRIVADO" not in json.dumps(corpo[nome])


def test_limite_defensivo_do_prompt_retira_rodadas_mais_antigas() -> None:
    historico = [CorrecaoAnterior([], f"correção {i}") for i in range(9)]

    corpo = _prompt(historico)

    assert [item["texto"] for item in corpo["dados_nao_confiaveis_da_correcao"]["historico"]] == [
        f"correção {i}" for i in range(4, 9)
    ]
