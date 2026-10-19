from decimal import Decimal

from app.busca_meta import LIMITE_CANDIDATOS, Ponto, escolher


def ponto(meta: str, comissao: str, id: str = "resultado") -> Ponto:
    return Ponto(Decimal(meta), Decimal(comissao), id)


def test_primeira_meta_e_proporcional_e_nao_um_resultado_estimado() -> None:
    passo = escolher([ponto("1000", "50")], Decimal("100"))
    assert passo.candidata == Decimal("2000")
    assert passo.vencedora is None


def test_expande_ate_encontrar_o_limite_e_depois_bissecta() -> None:
    pontos = [ponto("1000", "50"), ponto("2000", "90")]
    assert escolher(pontos, Decimal("100")).candidata == Decimal("4000")
    pontos.append(ponto("4000", "180"))
    assert escolher(pontos, Decimal("100")).candidata == Decimal("3000")


def test_retorna_a_maior_execucao_viavel_quando_intervalo_e_estreito() -> None:
    melhor = ponto("2000", "100", "melhor")
    passo = escolher([ponto("1000", "50"), melhor, ponto("2001", "101")], Decimal("100"))
    assert passo.vencedora == melhor
    assert passo.candidata is None


def test_monotonicidade_compara_por_meta_inclusive_na_bissecao() -> None:
    passo = escolher(
        [ponto("1000", "50"), ponto("4000", "110"), ponto("2000", "120")],
        Decimal("100"),
    )
    assert passo.motivo == "nao_monotonica"


def test_limite_sem_superior_nao_sugere_estimativa() -> None:
    pontos = [ponto(str(1000 * (2**i)), "0", str(i)) for i in range(LIMITE_CANDIDATOS + 1)]
    assert escolher(pontos, Decimal("100")).motivo == "intervalo_esgotado"


def test_limite_com_superior_retorna_melhor_candidata_simulada() -> None:
    pontos = [ponto("1000", "50")]
    pontos += [ponto(str(1100 + i * 100), "60", str(i)) for i in range(LIMITE_CANDIDATOS - 1)]
    pontos.append(ponto("10000", "200"))
    assert escolher(pontos, Decimal("100")).vencedora == pontos[-2]


def test_comissao_zero_nao_divide_por_zero() -> None:
    assert escolher([ponto("1000", "0")], Decimal("100")).candidata == Decimal("2000")


def test_margem_pequena_preserva_meta_fracionaria() -> None:
    inicial = ponto("1000", "99.99999")
    passo = escolher([inicial], Decimal("100"))
    assert passo.candidata is not None
    assert Decimal("1000") < passo.candidata < Decimal("1000.01")
    assert Decimal(str(float(passo.candidata))) == passo.candidata


def test_bissecao_encontra_viavel_entre_metas_separadas_por_um_centavo() -> None:
    inicial = ponto("1000", "99.99999")
    superior = ponto("1000.01", "100.0009899999")
    pontos = [inicial, superior]
    for _ in range(LIMITE_CANDIDATOS - 1):
        passo = escolher(pontos, Decimal("100"))
        if passo.vencedora is not None:
            assert passo.vencedora.meta > inicial.meta
            assert passo.vencedora.comissao <= Decimal("100")
            return
        assert passo.motivo is None
        assert passo.candidata is not None
        pontos.append(Ponto(passo.candidata, passo.candidata * Decimal("0.09999999"), "nova"))
    raise AssertionError("A busca deveria encontrar uma meta maior viável")
