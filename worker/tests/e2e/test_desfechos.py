"""Os desfechos de um comando, do RabbitMQ ao banco e de volta ao RabbitMQ (e2e).

O worker é o processo real. Cada teste publica um comando na fila do vhost, espera o evento nas
duas filas de consumidor e confere o que sobrou: uma linha no banco, a fila do comando vazia (nada
pronto e nada sem `ack`), a DLQ como esperado, nenhum container, e nenhum conteúdo do código gerado
no log. É o ciclo fechado: todo comando termina, e termina de um jeito que dá para consultar.
"""

import json
from typing import Any
from uuid import uuid4

import pytest

from tests.app.esquemas import erros_do_log
from tests.e2e import regras
from tests.e2e.apoio import Ambiente, Worker

pytestmark = pytest.mark.e2e

CAMPOS_DO_EVENTO_DE_ERRO = {"job_id", "resultado_id", "status"}


async def fechar_o_ciclo(
    ambiente: Ambiente, worker: Worker, semente: dict[str, Any], *, na_dlq: int = 0
) -> None:
    """O que precisa valer no fim de qualquer comando, seja qual for o desfecho."""
    contagem = await ambiente.corretor.esperar_comando_concluido()
    assert contagem.vazia, f"o comando ficou preso: {contagem}"
    assert ambiente.corretor.contagens()["executar-codigo.dlq"].prontas == na_dlq
    assert ambiente.conteineres_do_job(semente["job_id"]) == []
    assert worker.vivo, f"o worker caiu\n{worker.cauda()}"


@pytest.mark.parametrize(
    ("orcamento", "veredito"), [(485000.0, "inviavel"), (600000.0, "viavel")], ids=["acima", "cabe"]
)
async def test_sucesso_grava_a_linha_e_publica_o_evento_nas_duas_filas(
    ambiente: Ambiente, orcamento: float, veredito: str
) -> None:
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.SUCESSO, orcamento=orcamento)

    await ambiente.corretor.publicar_comando(semente, orcamento)
    da_api = await ambiente.corretor.evento(ambiente.corretor.api)
    do_codegen = await ambiente.corretor.evento(ambiente.corretor.codegen)

    (linha,) = await ambiente.linhas(semente["job_id"])
    assert (linha["status"], linha["veredito"]) == ("sucesso", veredito)
    totais = json.loads(linha["totais"])
    assert (totais["baseline"], totais["simulado"]) == (
        regras.BASELINE_2025_11,
        regras.SIMULADO_DO_EXEMPLO,
    )
    assert totais["orcamento"] == orcamento
    assert da_api == do_codegen
    assert da_api["resultado_id"] == str(linha["id"])
    assert (da_api["status"], da_api["veredito"]) == ("sucesso", veredito)
    await fechar_o_ciclo(ambiente, worker, semente)


async def test_todo_log_do_processamento_carrega_o_job_id(ambiente: Ambiente) -> None:
    """`job_id` é obrigatório em todo log emitido durante o processamento de um job (AGENTS.md,
    contracts/observability): sem ele não há como seguir um job entre os serviços."""
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.SUCESSO)

    await ambiente.corretor.publicar_comando(semente, 485000.0)
    await ambiente.corretor.evento(ambiente.corretor.api)
    await fechar_o_ciclo(ambiente, worker, semente)

    do_job = {r["message"] for r in worker.do_job(semente["job_id"])}
    assert do_job >= {
        "comando executar-codigo recebido",
        "execução preparada",
        "execução no sandbox concluída",
        "execução julgada",
        "resultado gravado",
        "simulacao-concluida publicada",
    }


async def test_assercao_violada_e_categoria_propria_e_sem_veredito(ambiente: Ambiente) -> None:
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.COMISSAO_NEGATIVA)

    await ambiente.corretor.publicar_comando(semente, 485000.0)
    evento = await ambiente.corretor.evento(ambiente.corretor.api)

    (linha,) = await ambiente.linhas(semente["job_id"])
    assert linha["status"] == "assercao_violada"
    assert (linha["veredito"], linha["totais"], linha["decomposicao"]) == (None, None, None)
    assert [a["resultado"] for a in json.loads(linha["assercoes"])] == ["violada"]
    assert set(evento) == CAMPOS_DO_EVENTO_DE_ERRO and evento["status"] == "assercao_violada"
    assert await ambiente.corretor.evento(ambiente.corretor.codegen) == evento
    await fechar_o_ciclo(ambiente, worker, semente)


async def test_erro_do_codigo_e_erro_codigo_e_nada_da_regra_chega_ao_log(
    ambiente: Ambiente,
) -> None:
    """A exceção, o stdout, o stderr e a própria fonte da regra são conteúdo não confiável: ficam
    no container, e o worker não os copia para o log. O orçamento também não."""
    orcamento = 487123.45
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.LEVANTA_COM_SEGREDOS, orcamento=orcamento)

    await ambiente.corretor.publicar_comando(semente, orcamento)
    evento = await ambiente.corretor.evento(ambiente.corretor.api)

    (linha,) = await ambiente.linhas(semente["job_id"])
    assert (linha["status"], linha["veredito"]) == ("erro_codigo", None)
    assert evento["status"] == "erro_codigo" and set(evento) == CAMPOS_DO_EVENTO_DE_ERRO
    (julgada,) = worker.mensagens("execução julgada")
    assert julgada["extra"]["motivo"] == "excecao"
    await fechar_o_ciclo(ambiente, worker, semente)

    log = worker.texto_do_log()
    for conteudo in (
        "SEGREDO-NO-STDOUT",
        "SEGREDO-NO-STDERR",
        "SEGREDO-NA-MENSAGEM",
        "SEGREDO-NA-FONTE",
        "aplicar_regra",
        "487123",
    ):
        assert conteudo not in log, f"{conteudo!r} vazou para o log do worker"


async def test_codigo_que_nao_termina_e_morto_no_prazo_e_o_ciclo_fecha(
    ambiente: Ambiente,
) -> None:
    """Um job pendurado é terminado, e não deixado rodando (o prazo real é de 60 s)."""
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.NAO_TERMINA)

    await ambiente.corretor.publicar_comando(semente, 485000.0)
    evento = await ambiente.corretor.evento(ambiente.corretor.api, prazo=150)

    (linha,) = await ambiente.linhas(semente["job_id"])
    assert (linha["status"], linha["veredito"]) == ("erro_codigo", None)
    assert evento["status"] == "erro_codigo"
    (concluida,) = worker.mensagens("execução no sandbox concluída")
    assert concluida["extra"]["estourou_timeout"] is True
    assert 55 <= concluida["extra"]["duracao_s"] <= 90
    (julgada,) = worker.mensagens("execução julgada")
    assert julgada["extra"]["motivo"] == "timeout"
    await fechar_o_ciclo(ambiente, worker, semente)


async def test_infra_esgotada_grava_e_publica_erro_infra_e_so_entao_vai_a_dlq(
    ambiente: Ambiente,
) -> None:
    """Sem a imagem do sandbox nenhum job executa: três tentativas, o desfecho gravado e
    publicado (senão o job ficaria em `simulando` para sempre), e o comando na DLQ."""
    worker = await ambiente.iniciar_worker(SANDBOX_IMAGE="synapse-sandbox:inexistente")
    semente = await ambiente.semear(regras.SUCESSO)

    await ambiente.corretor.publicar_comando(semente, 485000.0)
    da_api = await ambiente.corretor.evento(ambiente.corretor.api)
    do_codegen = await ambiente.corretor.evento(ambiente.corretor.codegen)

    (linha,) = await ambiente.linhas(semente["job_id"])
    assert linha["status"] == "erro_infra"
    assert (linha["veredito"], linha["totais"], linha["decomposicao"]) == (None, None, None)
    assert json.loads(linha["assercoes"]) == []
    assert da_api == do_codegen
    assert da_api["status"] == "erro_infra" and da_api["resultado_id"] == str(linha["id"])
    assert set(da_api) == CAMPOS_DO_EVENTO_DE_ERRO
    await fechar_o_ciclo(ambiente, worker, semente, na_dlq=1)

    assert len(worker.mensagens("execução julgada")) == 3, "eram três tentativas"
    assert len(worker.mensagens("resultado gravado")) == 1, "o erro_infra é gravado uma vez"
    (no_dlq,) = await ambiente.corretor.retirar_tudo(ambiente.corretor.dlq)
    assert json.loads(no_dlq.body)["job_id"] == str(semente["job_id"])
    assert no_dlq.headers["synapse_retry_count"] == 2


async def test_comando_ruim_vai_a_dlq_e_nao_trava_a_fila(ambiente: Ambiente) -> None:
    """Quatro jeitos de o comando ser inválido, um atrás do outro, e um comando bom no fim: os
    ruins vão para a DLQ sem deixar linha nem evento, e o bom é processado."""
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.SUCESSO)
    de_outro_job = await ambiente.semear(regras.SUCESSO)
    ruins = [
        b"isto nao e json",
        json.dumps({"job_id": str(uuid4())}).encode(),
        json.dumps(
            {
                "job_id": str(semente["job_id"]),
                "codigo_gerado_id": str(uuid4()),
                "competencias": ["2025-11"],
                "orcamento": 1.0,
            }
        ).encode(),
        json.dumps(
            {
                "job_id": str(de_outro_job["job_id"]),
                "codigo_gerado_id": str(semente["id"]),
                "competencias": ["2025-11"],
                "orcamento": 1.0,
            }
        ).encode(),
    ]
    for corpo in ruins:
        await ambiente.corretor.publicar(corpo)

    await ambiente.corretor.publicar_comando(semente, 485000.0)
    evento = await ambiente.corretor.evento(ambiente.corretor.api)

    assert evento["status"] == "sucesso"
    assert len(await ambiente.linhas(semente["job_id"])) == 1
    assert await ambiente.linhas(de_outro_job["job_id"]) == []
    await fechar_o_ciclo(ambiente, worker, semente, na_dlq=len(ruins))
    assert await ambiente.corretor.esperar(ambiente.corretor.api, prazo=2) is None


async def test_os_logs_do_processo_seguem_o_schema_de_log_do_monorepo(ambiente: Ambiente) -> None:
    """Toda linha que o processo real emite, num ciclo completo, contra
    `contracts/observability/log.schema.json`: é por esse envelope que os quatro serviços se
    correlacionam."""
    worker = await ambiente.iniciar_worker()
    semente = await ambiente.semear(regras.SUCESSO)
    await ambiente.corretor.publicar_comando(semente, 485000.0)
    await ambiente.corretor.evento(ambiente.corretor.api)
    await fechar_o_ciclo(ambiente, worker, semente)

    registros = worker.registros()
    assert len(registros) >= 8
    erros = {(r["message"], e) for r in registros for e in erros_do_log(r)}
    assert erros == set(), "linha de log fora do schema"
