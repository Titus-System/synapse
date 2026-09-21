"""O processo do worker: subir, atender, encerrar e falhar ao subir (e2e).

O que um operador vê: o processo só fica pronto quando a subida termina inteira, continua
respondendo enquanto um job executa, encerra sem perder o comando que estava em mãos e, quando não
tem como funcionar, recusa-se a subir em vez de subir e falhar no primeiro job.
"""

import signal
import time
from uuid import UUID

import pytest

from tests.e2e import regras
from tests.e2e.apoio import FILA_COMANDO, Ambiente, Worker, esperar_ate

pytestmark = pytest.mark.e2e

# O uvicorn encerra de forma graciosa e, no fim, reemite o SIGTERM que recebeu: o processo sai por
# sinal (-15), e é isso que o `docker stop` vê como 143. Ambos são um encerramento limpo.
ENCERRAMENTO_LIMPO = {0, -signal.SIGTERM}


async def test_sobe_pronto_com_a_topologia_e_um_consumidor(ambiente: Ambiente) -> None:
    worker = await ambiente.iniciar_worker()

    codigo, _ = await worker.saude()

    assert codigo == 200
    contagem = ambiente.corretor.contagens()[FILA_COMANDO]
    assert (contagem.consumidores, contagem.vazia) == (1, True)
    assert worker.mensagens("acesso ao daemon do Docker verificado")
    assert worker.mensagens("fila de execução declarada")


async def test_sigterm_ocioso_encerra_limpo_e_solta_o_consumidor(ambiente: Ambiente) -> None:
    worker = await ambiente.iniciar_worker()

    worker.sinalizar(signal.SIGTERM)
    saida = await worker.aguardar_saida(prazo=20)

    assert saida in ENCERRAMENTO_LIMPO, worker.cauda()
    assert worker.mensagens("conexão com o broker encerrada")
    contagem = await ambiente.corretor.esperar_fila(FILA_COMANDO, lambda c: c.consumidores == 0)
    assert contagem.vazia


async def _sigterm_no_meio_da_execucao(ambiente: Ambiente) -> tuple[UUID, Worker, float]:
    """Um job lento em andamento, o container no ar, e o worker recebendo SIGTERM."""
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.LENTA)
    job_id: UUID = semente["job_id"]
    await ambiente.corretor.publicar_comando(semente, 485000.0)
    await esperar_ate(
        lambda: bool(ambiente.conteineres_do_job(job_id)), "o container do job subir", prazo=30
    )
    inicio = time.monotonic()
    worker.sinalizar(signal.SIGTERM)
    saida = await worker.aguardar_saida(prazo=45)
    demora = time.monotonic() - inicio
    assert saida in ENCERRAMENTO_LIMPO, worker.cauda()
    return job_id, worker, demora


async def test_sigterm_no_meio_da_execucao_nao_perde_o_comando(ambiente: Ambiente) -> None:
    """O comando não foi confirmado, então o broker o devolve; um segundo worker o conclui, e o job
    termina com uma linha e um evento. Nunca sumiu."""
    corretor = ambiente.corretor
    job_id, _, _ = await _sigterm_no_meio_da_execucao(ambiente)

    contagem = await corretor.esperar_fila(FILA_COMANDO, lambda c: c.sem_ack == 0)
    linhas = await ambiente.linhas(job_id)
    assert contagem.prontas == 1 or len(linhas) == 1, (contagem, linhas)

    await ambiente.iniciar_worker()
    evento = await corretor.evento(corretor.api)
    (linha,) = await ambiente.linhas(job_id)
    assert evento["resultado_id"] == str(linha["id"])
    assert await corretor.esperar(corretor.api, prazo=2) is None, "evento duplicado"
    assert (await corretor.esperar_comando_concluido()).vazia


async def test_sigterm_no_meio_da_execucao_mata_e_remove_o_container_dentro_do_prazo_do_docker_stop(
    ambiente: Ambiente,
) -> None:
    """O uvicorn reemite o SIGTERM depois do desligamento gracioso, e o processo morre sem esperar
    threads: a limpeza do container tem de acontecer **durante** o desligamento, dentro dos 10 s
    que o `docker stop` dá antes do SIGKILL. O container seria um código sem quem lhe imponha o
    prazo de 60 s."""
    job_id, _, demora = await _sigterm_no_meio_da_execucao(ambiente)

    assert ambiente.conteineres_do_job(job_id) == [], "o encerramento deixou o container"
    assert demora < 10.0, f"o desligamento levou {demora:.1f} s, mais que o `docker stop`"


async def test_health_responde_enquanto_o_container_executa(ambiente: Ambiente) -> None:
    """O container é síncrono e leva segundos: se ele travasse o loop, o heartbeat do RabbitMQ e o
    healthcheck do compose parariam de responder no meio de um job."""
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.LENTA)
    await ambiente.corretor.publicar_comando(semente, 485000.0)
    await esperar_ate(
        lambda: bool(ambiente.conteineres_do_job(semente["job_id"])),
        "o container do job subir",
        prazo=30,
    )

    respostas = []
    while ambiente.conteineres_do_job(semente["job_id"]) and len(respostas) < 12:
        respostas.append(await worker.saude())

    assert len(respostas) >= 5, "o job terminou antes de medir"
    assert all(codigo == 200 for codigo, _ in respostas)
    assert max(demora for _, demora in respostas) < 1.0, respostas


async def test_dois_comandos_sao_processados_um_de_cada_vez(ambiente: Ambiente) -> None:
    """`prefetch` 1: o segundo comando só é entregue depois de o primeiro terminar."""
    worker = await ambiente.iniciar_worker()
    primeiro = await ambiente.semear(regras.SUCESSO)
    segundo = await ambiente.semear(regras.SUCESSO)
    await ambiente.corretor.publicar_comando(primeiro, 485000.0)
    await ambiente.corretor.publicar_comando(segundo, 485000.0)

    await ambiente.corretor.evento(ambiente.corretor.api)
    await ambiente.corretor.evento(ambiente.corretor.api)

    sequencia = [
        (r["message"], r["job_id"])
        for r in worker.registros()
        if r["message"] in {"comando executar-codigo recebido", "simulacao-concluida publicada"}
    ]
    ordem = [str(primeiro["job_id"]), str(segundo["job_id"])]
    assert sequencia == [
        ("comando executar-codigo recebido", ordem[0]),
        ("simulacao-concluida publicada", ordem[0]),
        ("comando executar-codigo recebido", ordem[1]),
        ("simulacao-concluida publicada", ordem[1]),
    ]
    assert (await ambiente.corretor.esperar_comando_concluido()).vazia


async def test_sem_acesso_ao_daemon_docker_o_worker_recusa_subir(ambiente: Ambiente) -> None:
    """Subir e falhar só no primeiro job seria o pior dos mundos: o comando seria consumido, ficaria
    em erro_infra e a causa apareceria três tentativas depois."""
    worker = await ambiente.iniciar_worker(
        esperar_pronto=False, DOCKER_HOST="unix:///nao/existe.sock"
    )

    saida = await worker.aguardar_saida(prazo=30)

    assert saida != 0
    assert "sem acesso ao daemon do Docker" in worker.texto_do_log()
    contagem = ambiente.corretor.contagens()[FILA_COMANDO]
    assert contagem.consumidores == 0


async def test_worker_que_nao_sobe_nao_toca_nos_comandos_da_fila(
    ambiente: Ambiente,
) -> None:
    """Um worker que morre na subida não pode ter tocado nos comandos da fila."""
    semente = await ambiente.semear(regras.SUCESSO)
    await ambiente.corretor.publicar_comando(semente, 485000.0)
    worker = await ambiente.iniciar_worker(
        esperar_pronto=False, DOCKER_HOST="unix:///nao/existe.sock"
    )

    await worker.aguardar_saida(prazo=30)

    contagem = ambiente.corretor.contagens()[FILA_COMANDO]
    assert (contagem.prontas, contagem.sem_ack) == (1, 0)
    assert await ambiente.linhas(semente["job_id"]) == []
