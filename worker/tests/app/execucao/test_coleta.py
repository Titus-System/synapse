"""A classificação do desfecho (T-065), sem subir container.

Cada teste monta a ``SaidaBruta`` que um container real produziria (ou uma que ele não
produziria: código hostil escreve qualquer byte no stdout) e exige **classe e motivo**. O que
está em jogo é a fronteira entre ``erro_infra``, que pede repetição, e o resto, que pede
regeneração: errar para o lado de ``erro_infra`` daria à regra um jeito de fugir dela.
"""

import copy
import json
from typing import Any

import pytest

from app.execucao.coleta import classificar, classificar_falha_de_infra
from app.execucao.container import SaidaBruta
from app.execucao.schema import validar_resultado
from app.sandbox.envelope import SAIDA_ASSERCAO_VIOLADA, SAIDA_ERRO_CODIGO, SAIDA_SUCESSO
from tests.app.execucao.envelopes import (
    ASSERCAO_OK,
    ASSERCAO_VIOLADA,
    FALHA,
    ORCAMENTO,
    PAYLOAD,
    RESULTADO,
    envelope,
    saida,
)


def classificar_saida(bruta: SaidaBruta) -> tuple[str, str]:
    desfecho = classificar(bruta, PAYLOAD, ORCAMENTO)
    return desfecho.classe, desfecho.motivo


# ---- sucesso ----


def test_sucesso_valido() -> None:
    bruta = saida(envelope())

    desfecho = classificar(bruta, PAYLOAD, ORCAMENTO)

    assert (desfecho.classe, desfecho.motivo) == ("sucesso", "ok")
    assert desfecho.assercoes == [ASSERCAO_OK]
    assert desfecho.saida is bruta


def test_o_resultado_de_sucesso_segue_exatamente_como_saiu_do_container() -> None:
    """Sem recomposição: nem números tocados, nem o orçamento acrescentado. A cópia que vai ao
    schema é outra."""
    bruta = saida(envelope())

    desfecho = classificar(bruta, PAYLOAD, ORCAMENTO)

    assert desfecho.resultado == json.loads(bruta.stdout)["resultado"]
    assert desfecho.resultado is not None
    assert "orcamento" not in desfecho.resultado["totais"]


def test_o_orcamento_e_acrescentado_so_para_validar() -> None:
    """O schema exige totais.orcamento; sem o acréscimo, todo resultado do container seria
    reprovado por um campo que ele não tem como enviar."""
    assert "orcamento" not in RESULTADO["totais"]
    assert validar_resultado(RESULTADO, ORCAMENTO) == []


# ---- o que o container não conta: prazo, memória, corte ----


def test_timeout_e_erro_codigo_mesmo_com_envelope_de_sucesso_completo() -> None:
    """Uma regra pode escrever o envelope e deixar uma thread viva: o processo só morre pelo
    nosso SIGKILL. O resultado é de um processo que não terminou limpo, e não vale."""
    bruta = saida(envelope(), codigo_saida=137, estourou_timeout=True)

    assert classificar_saida(bruta) == ("erro_codigo", "timeout")


def test_estouro_de_memoria_e_erro_codigo() -> None:
    bruta = saida(b"", codigo_saida=137, oom_killed=True)

    assert classificar_saida(bruta) == ("erro_codigo", "memoria")


def test_o_timeout_vence_a_memoria_quando_os_dois_aparecem() -> None:
    bruta = saida(b"", codigo_saida=137, estourou_timeout=True, oom_killed=True)

    assert classificar_saida(bruta) == ("erro_codigo", "timeout")


def test_saida_cortada_no_teto_nao_e_lida() -> None:
    """Um envelope cortado no meio é JSON inválido, mas o motivo certo é o corte."""
    bruta = saida(envelope(), stdout_truncado=True)

    assert classificar_saida(bruta) == ("erro_codigo", "saida_truncada")


@pytest.mark.parametrize("codigo_saida", [0, 1, 137, 143])
def test_sem_envelope_e_erro_do_codigo_seja_qual_for_o_codigo_de_saida(codigo_saida: int) -> None:
    """1 é o que o harness usa para "falhei eu", mas a regra roda no mesmo processo e forja
    isso com os._exit(1); 0 sem envelope é um os._exit(0); 137 e 143 são morte por sinal."""
    assert classificar_saida(saida(b"", codigo_saida=codigo_saida)) == (
        "erro_codigo",
        "sem_envelope",
    )


# ---- o envelope que não é envelope ----


def _sem(campo: str) -> dict[str, Any]:
    base = envelope()
    del base[campo]
    return base


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param(b"resultado: ok\n", id="texto solto"),
        pytest.param(b'{"versao":1}\n{"versao":1}\n', id="duas linhas"),
        pytest.param(b"[1,2,3]\n", id="json que nao e objeto"),
        pytest.param(b"{}\n", id="objeto vazio"),
        pytest.param(b'{"status":"sucesso"\n', id="json cortado"),
        pytest.param(b"\xff\xfe{}\n", id="nao e utf-8"),
        pytest.param(b"[" * 200_000 + b"\n", id="aninhamento que estoura o parser"),
        pytest.param(
            json.dumps(envelope())
            .replace('"diferenca_pct": 0.0245', '"diferenca_pct": NaN')
            .encode(),
            id="NaN",
        ),
        pytest.param(json.dumps(envelope()).replace("11788.0", "Infinity").encode(), id="Infinity"),
        pytest.param(envelope(versao=2), id="versao 2"),
        pytest.param(envelope(versao=True), id="versao booleana"),
        pytest.param(envelope(status="ok"), id="status desconhecido"),
        pytest.param(envelope(status=["sucesso"]), id="status nao hashavel"),
        pytest.param(envelope(competencias="2025-11"), id="competencias nao e lista"),
        pytest.param(envelope(competencias=[202511]), id="competencia nao e texto"),
        pytest.param(envelope(job_id=123), id="job_id nao e texto"),
        pytest.param(envelope(extra="campo a mais"), id="campo desconhecido"),
        pytest.param(_sem("erro"), id="campo faltando"),
        pytest.param(envelope(assercoes="ok"), id="assercoes nao e lista"),
        pytest.param(
            envelope(assercoes=[{"nome": "x", "resultado": "talvez"}]), id="assercao mal formada"
        ),
    ],
)
def test_o_que_nao_e_um_envelope_do_harness_e_erro_do_codigo(
    stdout: bytes | dict[str, Any],
) -> None:
    assert classificar_saida(saida(stdout)) == ("erro_codigo", "envelope_invalido")


def test_sucesso_com_assercao_violada_se_contradiz() -> None:
    """As duas cópias das asserções concordam entre si, então só a violação em si pode
    reprovar: uma invariante violada invalida o número, seja qual for o status escrito."""
    dados = envelope()
    dados["assercoes"] = [ASSERCAO_VIOLADA]
    dados["resultado"]["assercoes"] = [ASSERCAO_VIOLADA]

    assert classificar_saida(saida(dados)) == ("erro_codigo", "envelope_invalido")


def test_sucesso_cuja_copia_das_assercoes_diverge_do_resultado() -> None:
    dados = envelope()
    dados["assercoes"] = [{**ASSERCAO_OK, "nome": "outra_invariante"}]

    assert classificar_saida(saida(dados)) == ("erro_codigo", "envelope_invalido")


def test_sucesso_sem_resultado_ou_com_erro() -> None:
    assert classificar_saida(saida(envelope(resultado=None))) == (
        "erro_codigo",
        "envelope_invalido",
    )
    assert classificar_saida(saida(envelope(erro=dict(FALHA)))) == (
        "erro_codigo",
        "envelope_invalido",
    )


# ---- de quem é o envelope ----


@pytest.mark.parametrize(
    "mudanca",
    [
        {"job_id": "9c1f0a2e-7b34-4d1a-8e55-0a1b2c3d4e5f"},
        {"codigo_gerado_id": "9c1f0a2e-7b34-4d1a-8e55-0a1b2c3d4e5f"},
        {"competencias": ["2025-11"]},
        {"competencias": ["2025-11", "2025-08"]},
    ],
    ids=["job", "codigo", "competencias a menos", "competencias fora de ordem"],
)
def test_envelope_de_outra_execucao_nao_e_o_desta(mudanca: dict[str, Any]) -> None:
    assert classificar_saida(saida(envelope(**mudanca))) == (
        "erro_codigo",
        "envelope_de_outra_execucao",
    )


@pytest.mark.parametrize(
    "status,codigo_saida",
    [
        ("sucesso", SAIDA_ERRO_CODIGO),
        ("sucesso", 1),
        ("erro_codigo", SAIDA_SUCESSO),
        ("assercao_violada", SAIDA_SUCESSO),
    ],
)
def test_codigo_de_saida_que_contradiz_o_status_do_envelope(status: str, codigo_saida: int) -> None:
    """O harness sempre sai com o código do status que escreveu. Um envelope de sucesso que
    acompanhe uma saída 3 não foi escrito por ele."""
    assert classificar_saida(saida(envelope(status), codigo_saida)) == (
        "erro_codigo",
        "codigo_de_saida_divergente",
    )


# ---- asserção violada ----


def test_assercao_violada_e_categoria_propria() -> None:
    desfecho = classificar(
        saida(envelope("assercao_violada"), SAIDA_ASSERCAO_VIOLADA), PAYLOAD, ORCAMENTO
    )

    assert (desfecho.classe, desfecho.motivo) == ("assercao_violada", "assercao")
    assert desfecho.assercoes == [ASSERCAO_VIOLADA]
    assert desfecho.resultado is None


def test_assercao_violada_sem_nenhuma_violada_se_contradiz() -> None:
    bruta = saida(envelope("assercao_violada", assercoes=[ASSERCAO_OK]), SAIDA_ASSERCAO_VIOLADA)

    assert classificar_saida(bruta) == ("erro_codigo", "envelope_invalido")


def test_assercao_violada_com_resultado_se_contradiz() -> None:
    """Número inválido não vira resultado: um envelope que traga os dois quer ser lido como o
    que convém."""
    bruta = saida(
        envelope("assercao_violada", resultado=copy.deepcopy(RESULTADO)), SAIDA_ASSERCAO_VIOLADA
    )

    assert classificar_saida(bruta) == ("erro_codigo", "envelope_invalido")


# ---- exceção no código gerado ----


def test_excecao_no_codigo_gerado_e_erro_codigo() -> None:
    desfecho = classificar(saida(envelope("erro_codigo"), SAIDA_ERRO_CODIGO), PAYLOAD, ORCAMENTO)

    assert (desfecho.classe, desfecho.motivo) == ("erro_codigo", "excecao")
    assert desfecho.erro == FALHA
    assert desfecho.resultado is None


@pytest.mark.parametrize(
    "erro",
    [None, "KeyError", {"tipo": "KeyError"}, {**FALHA, "traceback": 1}, {**FALHA, "extra": "x"}],
    ids=["ausente", "texto", "incompleto", "campo nao e texto", "campo a mais"],
)
def test_erro_codigo_com_falha_mal_formada(erro: object) -> None:
    bruta = saida(envelope("erro_codigo", erro=erro), SAIDA_ERRO_CODIGO)

    assert classificar_saida(bruta) == ("erro_codigo", "envelope_invalido")


# ---- resultado fora do schema ----


def test_resultado_que_nao_valida_no_schema_e_erro_codigo_nao_sucesso_parcial() -> None:
    dados = envelope()
    del dados["resultado"]["decomposicao"]["loja"]

    desfecho = classificar(saida(dados), PAYLOAD, ORCAMENTO)

    assert (desfecho.classe, desfecho.motivo) == ("erro_codigo", "resultado_fora_do_schema")
    assert desfecho.resultado is None
    assert "$.decomposicao: required" in desfecho.problemas


def test_os_problemas_dizem_onde_falhou_e_nunca_o_valor() -> None:
    """O valor veio de código não confiável e os problemas podem ir a um log."""
    dados = envelope()
    dados["resultado"]["totais"]["baseline"] = "VALOR-SECRETO-DA-REGRA"

    desfecho = classificar(saida(dados), PAYLOAD, ORCAMENTO)

    assert desfecho.problemas == ("$.totais.baseline: type",)
    assert "VALOR-SECRETO" not in "".join(desfecho.problemas)


def test_o_container_nao_tem_como_conhecer_o_orcamento() -> None:
    """Um totais.orcamento na saída do container é impossível para o harness real: alguém o
    fabricou. Não passa adiante para a T-066 achar que veio dele."""
    dados = envelope()
    dados["resultado"]["totais"]["orcamento"] = 485000.0

    desfecho = classificar(saida(dados), PAYLOAD, ORCAMENTO)

    assert (desfecho.classe, desfecho.motivo) == ("erro_codigo", "resultado_fora_do_schema")
    assert desfecho.problemas == ("$.totais.orcamento: fornecido_pelo_container",)


# ---- erro de infraestrutura e o que não vaza ----


def test_falha_de_infraestrutura_e_erro_infra_sem_saida() -> None:
    desfecho = classificar_falha_de_infra()

    assert (desfecho.classe, desfecho.motivo) == ("erro_infra", "infra")
    assert desfecho.saida is None and desfecho.resultado is None and desfecho.assercoes == []


def test_o_repr_do_desfecho_nao_carrega_conteudo_do_container() -> None:
    """Quem registrar o objeto inteiro num log não pode vazar stdout, stderr nem a mensagem
    de erro da regra."""
    dados = envelope("erro_codigo")
    dados["erro"] = {**FALHA, "mensagem": "MENSAGEM-DA-REGRA"}
    bruta = saida(dados, SAIDA_ERRO_CODIGO, stderr=b"STDERR-DA-REGRA")

    texto = repr(classificar(bruta, PAYLOAD, ORCAMENTO))

    assert "erro_codigo" in texto and "excecao" in texto
    for conteudo in ("MENSAGEM-DA-REGRA", "STDERR-DA-REGRA", "sucesso"):
        assert conteudo not in texto
