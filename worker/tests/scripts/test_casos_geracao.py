"""O formato dos casos de geração e a comparação do avaliador (T-243), sem Docker.

A execução no sandbox está em ``test_avaliar_geracao_integration.py``. Aqui ficam o que os
casos versionados garantem, as recusas do formato e a lógica dos quatro desfechos, com
medições montadas à mão.
"""

import json
import shutil
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.sandbox.resultado import Totais
from scripts.avaliar_geracao import codigo_de_saida, main, relatorio_json, relatorio_texto
from scripts.casos_geracao import (
    DIRETORIO_CASOS,
    FALHA_ESPERADA,
    Avaliacao,
    Caso,
    CasoInvalidoError,
    Medicao,
    carregar_caso,
    carregar_casos,
    comparar,
    ler_esperado,
    serializar_esperado,
    tolerancia_do_periodo,
)

RAIZ_MONOREPO = Path(__file__).resolve().parents[3]
IDS = ["generico-admissao", "generico-aniversario-loja", "nucleo-controle"]


def caso(caso_id: str) -> Caso:
    return carregar_caso(DIRETORIO_CASOS / caso_id)


# ---- os casos versionados ----


def test_os_tres_casos_carregam_com_a_representacao_valida() -> None:
    assert [c.id for c in carregar_casos()] == IDS


@pytest.mark.parametrize("caso_id", IDS)
def test_cada_caso_tem_referencia_e_esperado_do_proprio_periodo(caso_id: str) -> None:
    alvo = caso(caso_id)

    assert alvo.referencia.is_file()
    ler_esperado(alvo)


def test_cada_caso_cobre_um_formato_de_periodo() -> None:
    """O padrão (o período inteiro), um subconjunto não seguido e um mês só."""
    assert caso("generico-admissao").competencias == (
        "2025-08",
        "2025-09",
        "2025-10",
        "2025-11",
        "2025-12",
    )
    assert caso("nucleo-controle").competencias == ("2025-08", "2025-11")
    assert caso("generico-aniversario-loja").competencias == ("2025-11",)


def test_o_generico_calculavel_tem_contribuicao_em_elem_1() -> None:
    esperado = ler_esperado(caso("generico-admissao"))

    assert esperado.classe == "sucesso"
    assert esperado.elemento is not None
    assert esperado.elemento["elem.1"] > 0
    assert esperado.elemento["nucleo.percentual"] != 0


def test_o_generico_impossivel_espera_a_falha_da_regra() -> None:
    assert ler_esperado(caso("generico-aniversario-loja")) == FALHA_ESPERADA


def test_o_caso_impossivel_usa_a_representacao_do_contrato() -> None:
    exemplo = RAIZ_MONOREPO / "contracts/examples/domain/representacao-regra-generico.json"

    assert caso("generico-aniversario-loja").representacao == json.loads(
        exemplo.read_text(encoding="utf-8")
    )


# ---- as recusas do formato ----


def copiar_caso(
    caso_id: str, destino: Path, alterar: Callable[[dict[str, Any]], None] | None = None
) -> Path:
    pasta = destino / caso_id
    shutil.copytree(DIRETORIO_CASOS / caso_id, pasta)
    if alterar is not None:
        arquivo = pasta / "caso.json"
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        alterar(dados)
        arquivo.write_text(json.dumps(dados), encoding="utf-8")
    return pasta


def sem_nucleo(dados: dict[str, Any]) -> None:
    del dados["representacao"]["nucleo"]


def elemento_sem_ref(dados: dict[str, Any]) -> None:
    del dados["representacao"]["especificacoes"][0]["ref"]


def com_julho(dados: dict[str, Any]) -> None:
    dados["competencias"] = ["2025-07", "2025-08"]


def fora_de_ordem(dados: dict[str, Any]) -> None:
    dados["competencias"] = ["2025-11", "2025-08"]


def periodo_vazio(dados: dict[str, Any]) -> None:
    dados["competencias"] = []


def sem_leitura(dados: dict[str, Any]) -> None:
    dados["leitura"] = " "


def com_campo_a_mais(dados: dict[str, Any]) -> None:
    dados["orcamento"] = 1.0


def outro_id(dados: dict[str, Any]) -> None:
    dados["id"] = "outro"


@pytest.mark.parametrize(
    "alterar",
    [
        sem_nucleo,
        elemento_sem_ref,
        com_julho,
        fora_de_ordem,
        periodo_vazio,
        sem_leitura,
        com_campo_a_mais,
        outro_id,
    ],
)
def test_caso_fora_do_formato_e_recusado(
    tmp_path: Path, alterar: Callable[[dict[str, Any]], None]
) -> None:
    pasta = copiar_caso("generico-admissao", tmp_path, alterar)

    with pytest.raises(CasoInvalidoError):
        carregar_caso(pasta)


def test_caso_sem_referencia_e_recusado(tmp_path: Path) -> None:
    pasta = copiar_caso("nucleo-controle", tmp_path)
    (pasta / "referencia.py").unlink()

    with pytest.raises(CasoInvalidoError, match="referencia.py"):
        carregar_caso(pasta)


def test_esperado_gravado_para_outro_periodo_e_recusado(tmp_path: Path) -> None:
    def so_agosto(dados: dict[str, Any]) -> None:
        dados["competencias"] = ["2025-08"]

    alvo = carregar_caso(copiar_caso("nucleo-controle", tmp_path, so_agosto))

    with pytest.raises(CasoInvalidoError, match="outro período"):
        ler_esperado(alvo)


def test_esperado_com_falha_diferente_da_esperada_e_recusado(tmp_path: Path) -> None:
    alvo = carregar_caso(copiar_caso("generico-aniversario-loja", tmp_path))
    falha = Medicao("erro_codigo", "excecao", tipo_erro="KeyError")
    alvo.esperado.write_text(serializar_esperado(alvo, falha), encoding="utf-8")

    with pytest.raises(CasoInvalidoError, match="falha diferente"):
        ler_esperado(alvo)


@pytest.mark.parametrize("caso_id", IDS)
def test_o_esperado_serializado_volta_igual(tmp_path: Path, caso_id: str) -> None:
    alvo = carregar_caso(copiar_caso(caso_id, tmp_path))
    gravado = alvo.esperado.read_text(encoding="utf-8")

    assert serializar_esperado(alvo, ler_esperado(alvo)) == gravado


# ---- a comparação ----

ESPERADO = Medicao(
    "sucesso",
    "ok",
    totais=Totais(baseline=900.0, simulado=1000.0, diferenca_abs=100.0, diferenca_pct=0.1),
    elemento={"nucleo.percentual": 60.0, "elem.1": 40.0},
)


def obtido(simulado: float, elemento: dict[str, float]) -> Medicao:
    return Medicao(
        "sucesso",
        "ok",
        totais=Totais(
            baseline=900.0,
            simulado=simulado,
            diferenca_abs=round(simulado - 900.0, 2),
            diferenca_pct=round((simulado - 900.0) / 900.0, 6),
        ),
        elemento=elemento,
    )


def comparar_um_centavo(caso_id: str, esperado: Medicao, medido: Medicao) -> Avaliacao:
    """A tolerância de um período com uma linha só, a menor que um caso pode ter."""
    return comparar(caso_id, esperado, medido, Decimal("0.01"))


@pytest.mark.parametrize(
    ("caso_id", "tolerancia"),
    [
        ("generico-admissao", Decimal("26.72")),
        ("nucleo-controle", Decimal("10.43")),
        ("generico-aniversario-loja", Decimal("5.46")),
    ],
)
def test_a_tolerancia_e_um_centavo_por_linha_do_periodo(caso_id: str, tolerancia: Decimal) -> None:
    """497, 530, 537, 546 e 562 linhas de agosto a dezembro, no manifesto dos baselines."""
    assert tolerancia_do_periodo(caso(caso_id).competencias) == tolerancia


def test_a_tolerancia_maior_absorve_o_arredondamento_de_varias_linhas() -> None:
    medido = obtido(1000.03, {"nucleo.percentual": 60.02, "elem.1": 40.01})

    assert comparar_um_centavo("c", ESPERADO, medido).desfecho == "diverge"
    assert comparar("c", ESPERADO, medido, Decimal("0.03")).desfecho == "bate"


def test_o_mesmo_resultado_bate() -> None:
    avaliacao = comparar_um_centavo(
        "c", ESPERADO, obtido(1000.0, {"nucleo.percentual": 60.0, "elem.1": 40.0})
    )

    assert (avaliacao.desfecho, avaliacao.diferencas, avaliacao.passou) == ("bate", (), True)


def test_um_centavo_de_diferenca_ainda_bate() -> None:
    avaliacao = comparar_um_centavo(
        "c", ESPERADO, obtido(1000.01, {"nucleo.percentual": 60.0, "elem.1": 40.01})
    )

    assert avaliacao.desfecho == "bate"


def test_dois_centavos_num_elemento_divergem_e_o_elemento_e_apontado() -> None:
    avaliacao = comparar_um_centavo(
        "c", ESPERADO, obtido(1000.02, {"nucleo.percentual": 60.0, "elem.1": 40.02})
    )

    assert avaliacao.desfecho == "diverge"
    assert [(d.elemento, d.esperado, d.obtido) for d in avaliacao.diferencas] == [
        ("elem.1", 40.0, 40.02)
    ]


def test_total_divergente_reprova_mesmo_com_os_elementos_iguais() -> None:
    avaliacao = comparar_um_centavo(
        "c", ESPERADO, obtido(1000.5, {"nucleo.percentual": 60.0, "elem.1": 40.0})
    )

    assert (avaliacao.desfecho, avaliacao.diferencas) == ("diverge", ())


def test_elemento_ausente_vale_zero() -> None:
    """A decomposição só tem chave para elemento com contribuição."""
    com_zero = Medicao(
        "sucesso",
        "ok",
        totais=ESPERADO.totais,
        elemento={"nucleo.percentual": 100.0, "elem.1": 0.0},
    )

    assert (
        comparar_um_centavo("c", com_zero, obtido(1000.0, {"nucleo.percentual": 100.0})).desfecho
        == "bate"
    )


def test_elemento_que_o_esperado_nao_tem_diverge() -> None:
    avaliacao = comparar_um_centavo(
        "c", ESPERADO, obtido(1000.0, {"nucleo.percentual": 60.0, "elem.1": 30.0, "elem.2": 10.0})
    )

    assert avaliacao.desfecho == "diverge"
    assert [d.elemento for d in avaliacao.diferencas] == ["elem.1", "elem.2"]


@pytest.mark.parametrize(
    "falha",
    [
        FALHA_ESPERADA,
        Medicao("erro_codigo", "timeout"),
        Medicao("assercao_violada", "assercao"),
        Medicao("erro_codigo", "baseline_divergente"),
    ],
)
def test_falha_num_caso_que_espera_numero_e_falhou_sem_esperar(falha: Medicao) -> None:
    avaliacao = comparar_um_centavo("c", ESPERADO, falha)

    assert (avaliacao.desfecho, avaliacao.passou) == ("falhou_sem_esperar", False)


def test_a_falha_esperada_passa() -> None:
    avaliacao = comparar_um_centavo("c", FALHA_ESPERADA, FALHA_ESPERADA)

    assert (avaliacao.desfecho, avaliacao.passou) == ("falhou_como_esperado", True)


def test_numero_num_caso_que_espera_falha_diverge() -> None:
    avaliacao = comparar_um_centavo("c", FALHA_ESPERADA, ESPERADO)

    assert (avaliacao.desfecho, avaliacao.passou) == ("diverge", False)


@pytest.mark.parametrize(
    "falha",
    [
        Medicao("erro_codigo", "excecao", tipo_erro="KeyError"),
        Medicao("erro_codigo", "excecao", tipo_erro="ValueError"),
        Medicao("erro_codigo", "timeout"),
        Medicao("erro_codigo", "sem_envelope"),
        Medicao("erro_codigo", "resultado_fora_do_schema"),
        Medicao("assercao_violada", "assercao"),
    ],
)
def test_outra_falha_num_caso_que_espera_falha_nao_conta_como_esperada(falha: Medicao) -> None:
    """Só NotImplementedError é recusa deliberada; um bug ou um timeout também param o job,
    mas não provam que a geração reconheceu o elemento impossível."""
    avaliacao = comparar_um_centavo("c", FALHA_ESPERADA, falha)

    assert (avaliacao.desfecho, avaliacao.passou) == ("falhou_sem_esperar", False)


# ---- o relatório e o código de saída ----


def avaliacoes_misturadas() -> list[Avaliacao]:
    return [
        comparar_um_centavo(
            "a", ESPERADO, obtido(1000.0, {"nucleo.percentual": 60.0, "elem.1": 40.0})
        ),
        comparar_um_centavo(
            "b", ESPERADO, obtido(1000.5, {"nucleo.percentual": 60.0, "elem.1": 40.5})
        ),
        comparar_um_centavo("c", FALHA_ESPERADA, FALHA_ESPERADA),
        comparar_um_centavo(
            "d", FALHA_ESPERADA, Medicao("erro_codigo", "excecao", tipo_erro="SegredoError")
        ),
    ]


def test_o_codigo_de_saida_so_e_zero_quando_todos_passam() -> None:
    avaliacoes = avaliacoes_misturadas()

    assert codigo_de_saida([avaliacoes[0], avaliacoes[2]]) == 0
    assert codigo_de_saida(avaliacoes) == 1


def test_o_relatorio_em_texto_traz_o_desfecho_o_total_e_o_elemento() -> None:
    texto = relatorio_texto(avaliacoes_misturadas())

    assert texto.splitlines() == [
        "a: bate",
        "  total simulado: esperado 1000.00, obtido 1000.00 (tolerância 0.01)",
        "b: diverge",
        "  total simulado: esperado 1000.00, obtido 1000.50 (tolerância 0.01)",
        "  elem.1: esperado 40.00, obtido 40.50",
        "c: falhou como esperado (erro_codigo/excecao)",
        "d: falhou sem esperar (erro_codigo/excecao)",
        "2 de 4 casos passaram",
    ]


def test_o_relatorio_em_json_traz_o_mesmo() -> None:
    relatorio = json.loads(relatorio_json(avaliacoes_misturadas()))

    assert [(r["caso"], r["desfecho"], r["passou"]) for r in relatorio] == [
        ("a", "bate", True),
        ("b", "diverge", False),
        ("c", "falhou_como_esperado", True),
        ("d", "falhou_sem_esperar", False),
    ]
    assert relatorio[1]["diferencas"] == [{"elemento": "elem.1", "esperado": 40.0, "obtido": 40.5}]


def test_o_relatorio_nao_mostra_o_tipo_do_erro_do_codigo_gerado() -> None:
    """O tipo da exceção vem de dentro do container: é comparado, nunca exibido."""
    avaliacoes = avaliacoes_misturadas()

    assert "SegredoError" not in relatorio_texto(avaliacoes)
    assert "SegredoError" not in relatorio_json(avaliacoes)


def test_sem_o_arquivo_de_um_caso_o_avaliador_sai_com_2_sem_executar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "nucleo-controle.py").write_text("", encoding="utf-8")

    assert main(["--codigo", str(tmp_path)]) == 2
    assert "generico-admissao.py, generico-aniversario-loja.py" in capsys.readouterr().err


def test_caso_inexistente_sai_com_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--codigo", str(tmp_path), "--caso", "nao-existe"]) == 2
    assert "nao-existe" in capsys.readouterr().err
