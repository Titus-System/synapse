"""Reentrega e queda do worker no meio de um comando (e2e).

A entrega do RabbitMQ é "pelo menos uma vez": um comando pode voltar depois de já ter resultado, ou
depois de o worker cair sem ter confirmado nada. Nos dois casos o job termina com **um** resultado e
**um** evento, e nenhum comando se perde.
"""

import json

import pytest

from tests.e2e import regras
from tests.e2e.apoio import FILA_COMANDO, Ambiente, esperar_ate

pytestmark = pytest.mark.e2e


async def test_comando_duplicado_nao_duplica_a_linha_nem_executa_de_novo(
    ambiente: Ambiente,
) -> None:
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.SUCESSO)
    corretor = ambiente.corretor
    await corretor.publicar_comando(semente, 485000.0)
    primeiro = await corretor.evento(corretor.api)
    await corretor.evento(corretor.codegen)

    await corretor.publicar_comando(semente, 485000.0)  # a entrega duplicada
    segundo = await corretor.evento(corretor.api)
    await corretor.evento(corretor.codegen)

    assert segundo == primeiro, "a reentrega tem de republicar o mesmo evento"
    (linha,) = await ambiente.linhas(semente["job_id"])
    assert primeiro["resultado_id"] == str(linha["id"])
    assert len(worker.mensagens("execução no sandbox concluída")) == 1, "executou de novo"
    assert len(worker.mensagens("resultado gravado")) == 1
    assert (
        len(
            worker.mensagens("resultado já gravado; o evento será republicado sem executar de novo")
        )
        == 1
    )
    assert (await corretor.esperar_comando_concluido()).vazia
    assert ambiente.conteineres_do_job(semente["job_id"]) == []


async def test_worker_morto_no_meio_da_execucao_nao_perde_o_comando(ambiente: Ambiente) -> None:
    """`kill -9` com o container rodando: o comando não foi confirmado, então o broker o devolve.
    Um segundo worker o conclui, e o job termina com uma linha e um evento só."""
    corretor = ambiente.corretor
    primeiro = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.LENTA)
    job_id = semente["job_id"]
    await corretor.publicar_comando(semente, 485000.0)
    await esperar_ate(
        lambda: bool(ambiente.conteineres_do_job(job_id)), "o container do job subir", prazo=30
    )

    primeiro.matar()

    orfaos = set(ambiente.conteineres_do_job(job_id))
    contagem = await corretor.esperar_fila(
        FILA_COMANDO, lambda c: c.prontas == 1 and c.sem_ack == 0, prazo=30
    )
    assert contagem.consumidores == 0
    assert await ambiente.linhas(job_id) == [], "o worker morto não gravou nada"
    assert await corretor.esperar(corretor.api, prazo=1) is None

    segundo = await ambiente.iniciar_worker()
    evento = await corretor.evento(corretor.api)
    assert await corretor.evento(corretor.codegen) == evento

    (linha,) = await ambiente.linhas(job_id)
    assert (linha["status"], linha["veredito"]) == ("sucesso", "inviavel")
    assert evento["resultado_id"] == str(linha["id"])
    assert await corretor.esperar(corretor.api, prazo=2) is None, "evento duplicado"
    assert (await corretor.esperar_comando_concluido()).vazia
    assert len(segundo.mensagens("resultado gravado")) == 1
    # O container do worker morto é órfão até o watchdog (T-068); o do segundo foi removido.
    assert set(ambiente.conteineres_do_job(job_id)) <= orfaos
    assert corretor.contagens()["executar-codigo.dlq"].prontas == 0
    assert json.loads(json.dumps(evento))["status"] == "sucesso"
