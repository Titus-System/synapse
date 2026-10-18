"""T-224: consulta da cadeia pelo mesmo job, somente com SELECT e limite fixo."""

from uuid import UUID, uuid4

from app.repositorio.rodadas_correcao import (
    LIMITE_HISTORICO_CORRECOES,
    CorrecaoAnterior,
    buscar_historico_correcao,
)
from tests.app.extracao_falsa import BancoExtracaoFalso


def _rodada(
    banco: BancoExtracaoFalso,
    job: UUID,
    anterior: UUID | None,
    texto: str,
    numero: int,
) -> tuple[UUID, UUID]:
    rodada, submissao = uuid4(), uuid4()
    banco.rodadas_correcao.append(
        {
            "id": rodada,
            "job_id": job,
            "rodada_anterior_id": anterior,
            "submissao_correcao_id": submissao,
            "conflitos": [{"elementos": [f"elem.{numero}"], "motivo": f"conflito {numero}"}],
        }
    )
    banco.transcricoes[submissao] = texto
    return rodada, submissao


async def test_primeira_correcao_sem_rodada_devolve_historico_vazio() -> None:
    banco = BancoExtracaoFalso()

    historico = await buscar_historico_correcao(banco, uuid4(), uuid4())

    assert historico == []
    assert len(banco.sql_executado) == 1
    assert banco.sql_executado[0].startswith("WITH RECURSIVE cadeia AS")
    assert "INSERT" not in banco.sql_executado[0]
    assert "UPDATE" not in banco.sql_executado[0]
    assert "DELETE" not in banco.sql_executado[0]


async def test_terceira_correcao_inclui_duas_anteriores_com_conflitos_e_textos() -> None:
    banco, job = BancoExtracaoFalso(), uuid4()
    primeira, _ = _rodada(banco, job, None, "Primeira correção privada", 1)
    segunda, _ = _rodada(banco, job, primeira, "Segunda correção privada", 2)
    _, atual = _rodada(banco, job, segunda, "Texto corrente", 3)

    historico = await buscar_historico_correcao(banco, job, atual)

    assert historico == [
        CorrecaoAnterior(
            [{"elementos": ["elem.1"], "motivo": "conflito 1"}], "Primeira correção privada"
        ),
        CorrecaoAnterior(
            [{"elementos": ["elem.2"], "motivo": "conflito 2"}], "Segunda correção privada"
        ),
    ]


async def test_historico_so_tem_cinco_ancestrais_mais_recentes() -> None:
    banco, job = BancoExtracaoFalso(), uuid4()
    anterior: UUID | None = None
    submissao = uuid4()
    for numero in range(1, 10):
        anterior, submissao = _rodada(banco, job, anterior, f"correção {numero}", numero)

    historico = await buscar_historico_correcao(banco, job, submissao)

    assert len(historico) == LIMITE_HISTORICO_CORRECOES
    assert [item.texto for item in historico] == [f"correção {i}" for i in range(4, 9)]
    assert all(item.conflitos for item in historico)


async def test_nunca_percorre_antecessor_pertencente_a_outro_job() -> None:
    banco, job, estranho = BancoExtracaoFalso(), uuid4(), uuid4()
    rodada_estranha, _ = _rodada(banco, estranho, None, "SEGREDO DE OUTRO JOB", 1)
    _, atual = _rodada(banco, job, rodada_estranha, "Minha correção", 2)

    historico = await buscar_historico_correcao(banco, job, atual)

    assert historico == []
    sql = banco.sql_executado[0]
    assert "anterior.job_id = :job_id" in sql
    assert "r.job_id = :job_id" in sql
    assert "submissao_correcao_id = :submissao_id" in sql


async def test_rodada_anterior_sem_texto_nao_entra_no_contexto() -> None:
    banco, job = BancoExtracaoFalso(), uuid4()
    primeira, submissao_antiga = _rodada(banco, job, None, "", 1)
    _, atual = _rodada(banco, job, primeira, "Texto corrente", 2)
    banco.transcricoes[submissao_antiga] = None

    assert await buscar_historico_correcao(banco, job, atual) == []


async def test_historico_inclui_rodada_de_reextracao_que_falhou() -> None:
    banco, job = BancoExtracaoFalso(), uuid4()
    primeira, _ = _rodada(banco, job, None, "Correção cuja reextração falhou", 1)
    banco.rodadas_correcao[0]["estado"] = "reextracao_falhou"
    _, atual = _rodada(banco, job, primeira, "Correção atual", 2)

    historico = await buscar_historico_correcao(banco, job, atual)

    assert [item.texto for item in historico] == ["Correção cuja reextração falhou"]
    assert "estado" not in banco.sql_executado[0]
