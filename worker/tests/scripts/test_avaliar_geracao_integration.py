"""Os casos de geração e o avaliador contra a imagem real do sandbox (T-243).

Cada referência roda no container pelo mesmo caminho da fila e precisa reproduzir o esperado
gravado. O avaliador precisa aprovar as referências e reprovar um código que calcula errado,
que devolve número onde a regra não pode ser simulada ou que falha pelo motivo errado. Nada
aqui depende de Postgres nem de RabbitMQ.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.avaliar_geracao import avaliar, main
from scripts.casos_geracao import (
    DIRETORIO_CASOS,
    Caso,
    carregar_caso,
    carregar_casos,
    comparar,
    ler_esperado,
    serializar_esperado,
)
from scripts.gravar_esperado import medir_referencia

pytestmark = pytest.mark.docker

RAIZ_MONOREPO = Path(__file__).resolve().parents[3]
EXEMPLO_DO_HARNESS = (RAIZ_MONOREPO / "contracts" / "harness" / "exemplo" / "regra.py").read_text(
    encoding="utf-8"
)

# Implementa o núcleo do caso impossível e declara elem.1 com efeito zero: o pior erro que o
# contrato do harness descreve, um número que parece completo sem a parte da regra que faltou.
CODIGO_QUE_ZERA_O_ELEMENTO_IMPOSSIVEL = """
def aplicar_regra(bases, apuracao_base, competencias):
    vendas = bases["vendas"]
    venda = vendas.groupby(["matricula", "competencia"], as_index=False)["vlr_venda"].sum()
    simulada = apuracao_base.merge(venda, on=["matricula", "competencia"], how="left")
    simulada["vlr_venda"] = simulada["vlr_venda"].fillna(0.0)
    no_alvo = (
        (simulada["cod_loja"] == 13)
        & (simulada["cod_cargo"] == 100)
        & (simulada["competencia"] == "2025-11")
    )
    nova = simulada["comissao"].where(~no_alvo, simulada["vlr_venda"] * 0.02)
    delta = nova - simulada["comissao"]
    simulada["comissao"] = nova
    contribuicoes = apuracao_base[
        ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]
    ].copy()
    contribuicoes["elemento_ref"] = "nucleo.percentual"
    contribuicoes["delta"] = delta.to_numpy()
    contribuicoes = contribuicoes[contribuicoes["delta"] != 0.0]
    return {
        "apuracao_simulada": simulada.drop(columns="vlr_venda"),
        "contribuicoes": contribuicoes,
        "elementos_implementados": ["nucleo.percentual", "elem.1"],
    }
"""

# Para o job, mas por um bug, e não por reconhecer que elem.1 não cabe nos dados.
CODIGO_QUE_QUEBRA_COM_KEYERROR = """
def aplicar_regra(bases, apuracao_base, competencias):
    return bases["aniversarios_de_loja"]
"""


def caso(caso_id: str) -> Caso:
    return carregar_caso(DIRETORIO_CASOS / caso_id)


def referencia(caso_id: str) -> str:
    return caso(caso_id).referencia.read_text(encoding="utf-8")


@pytest.mark.parametrize("alvo", carregar_casos(), ids=lambda alvo: alvo.id)
def test_a_referencia_reproduz_o_esperado_gravado(alvo: Caso, imagem: str) -> None:
    medicao = medir_referencia(alvo, imagem=imagem)

    assert serializar_esperado(alvo, medicao) == alvo.esperado.read_text(encoding="utf-8")
    assert comparar(alvo.id, ler_esperado(alvo), medicao, Decimal(0)).passou


def test_o_avaliador_aprova_as_tres_referencias_e_sai_com_zero(
    tmp_path: Path, imagem: str, capsys: pytest.CaptureFixture[str]
) -> None:
    for alvo in carregar_casos():
        (tmp_path / f"{alvo.id}.py").write_text(referencia(alvo.id), encoding="utf-8")

    codigo = main(["--codigo", str(tmp_path), "--imagem", imagem])

    saida = capsys.readouterr().out
    assert codigo == 0, saida
    assert saida.splitlines()[-1] == "3 de 3 casos passaram"


def test_o_avaliador_reprova_elem_1_alterado_aponta_o_elemento_e_sai_com_um(
    tmp_path: Path, imagem: str, capsys: pytest.CaptureFixture[str]
) -> None:
    original = referencia("generico-admissao")
    alterada = original.replace("_ACRESCIMO = 0.01", "_ACRESCIMO = 0.02")
    assert alterada != original
    (tmp_path / "generico-admissao.py").write_text(alterada, encoding="utf-8")

    codigo = main(
        ["--codigo", str(tmp_path), "--caso", "generico-admissao", "--imagem", imagem, "--json"]
    )

    [relatorio] = json.loads(capsys.readouterr().out)
    assert codigo == 1
    assert (relatorio["desfecho"], relatorio["passou"]) == ("diverge", False)
    assert [d["elemento"] for d in relatorio["diferencas"]] == ["elem.1"]
    [diferenca] = relatorio["diferencas"]
    assert diferenca["obtido"] > 1.9 * diferenca["esperado"]


def test_o_avaliador_reprova_numero_no_caso_impossivel(imagem: str) -> None:
    avaliacao = avaliar(
        caso("generico-aniversario-loja"), CODIGO_QUE_ZERA_O_ELEMENTO_IMPOSSIVEL, imagem=imagem
    )

    assert avaliacao.obtido.classe == "sucesso"
    assert (avaliacao.desfecho, avaliacao.passou) == ("diverge", False)


def test_falha_por_bug_no_caso_impossivel_nao_conta_como_esperada(imagem: str) -> None:
    avaliacao = avaliar(
        caso("generico-aniversario-loja"), CODIGO_QUE_QUEBRA_COM_KEYERROR, imagem=imagem
    )

    assert (avaliacao.obtido.classe, avaliacao.obtido.motivo) == ("erro_codigo", "excecao")
    assert (avaliacao.desfecho, avaliacao.passou) == ("falhou_sem_esperar", False)


def test_o_exemplo_do_harness_bate_com_o_caso_de_controle(imagem: str) -> None:
    avaliacao = avaliar(caso("nucleo-controle"), EXEMPLO_DO_HARNESS, imagem=imagem)

    assert (avaliacao.desfecho, avaliacao.diferencas) == ("bate", ())
    assert avaliacao.obtido == ler_esperado(caso("nucleo-controle"))


def test_uma_formula_equivalente_bate_apesar_do_arredondamento_por_linha(imagem: str) -> None:
    """`venda / 40` é `venda * 0.025`, mas o float arredonda para o outro lado algumas das linhas
    que caem em meio centavo: o total sai alguns centavos diferente. Com um centavo de tolerância
    no total, um código correto seria reprovado; com um centavo por linha, ele passa."""
    original = referencia("nucleo-controle")
    equivalente = original.replace("venda * _PERCENTUAL", "venda / 40")
    assert equivalente != original

    avaliacao = avaliar(caso("nucleo-controle"), equivalente, imagem=imagem)

    assert avaliacao.obtido != ler_esperado(caso("nucleo-controle"))
    assert (avaliacao.desfecho, avaliacao.diferencas) == ("bate", ())
