"""Reextração de uma correção (T-221) pelo consumer, roteador, grafo e nó reais.

Banco, produtores e modelo são os falsos do repositório; a leitura da regra é trocada por um
falso porque a consulta real tem os próprios testes (`tests/app/repositorio/test_regras.py`).
"""

import asyncio
import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import simplejson
from google.genai.errors import ServerError
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker
from langchain_core.messages import AIMessage
from langgraph.types import StateSnapshot

from app.contratos.mensagens import CorrecaoSubmetida
from app.core.logger import FormatadorJson, ManipuladorFilaContexto, job_id_ctx, no_ctx
from app.extracao.vocabulario import carregar_vocabulario
from app.graph.core.engine import build_graph
from app.graph.core.llm import disponibilidade
from app.mensageria.consumers import Consumer
from app.mensageria.roteamento import thread_da_correcao
from app.repositorio.artefatos import id_do_evento_de_trilha
from app.repositorio.encerramentos import EstadoDoEncerramento
from app.repositorio.regras import RegraInvalidaError
from app.representacao_regra import RepresentacaoRegra
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.extracao_falsa import BancoExtracaoFalso
from tests.app.graph.conftest import FakeChatModel
from tests.app.graph.test_extracao import amostra
from tests.app.graph.test_indisponibilidade_do_provedor import Relogio
from tests.app.test_mensageria import CONTRATOS, oficial

TEXTO = "O percentual passa para 3% e o orçamento passa a ser R$ 600 mil. CORRECAO_PRIVADA"
# Sem percentual: a validação de domínio aponta o conflito que a correção responde.
REGRA = {"nucleo": {"loja": ["13"]}, "especificacoes": []}
MOTIVO_DO_CONFLITO = "percentual ausente"
PERCENTUAL = {
    "tipo": "definir_nucleo",
    "trecho": "3%",
    "campo": "percentual",
    "valor": {"valor": Decimal("0.03"), "trecho": "3%"},
}
ORCAMENTO = {
    "tipo": "definir_parametro",
    "trecho": "R$ 600 mil",
    "campo": "orcamento",
    "valor": {"valor": 600000, "trecho": "R$ 600 mil"},
}
SAIDA = {"operacoes": [PERCENTUAL]}


@pytest.fixture
def logs() -> Iterator[list[dict[str, Any]]]:
    envelopes: list[dict[str, Any]] = []

    class Captura(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            preparado = ManipuladorFilaContexto(None).prepare(record)
            envelopes.append(simplejson.loads(FormatadorJson().format(preparado)))

    logger = logging.getLogger("app")
    handler = Captura()
    nivel = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield envelopes
    finally:
        logger.removeHandler(handler)
        logger.setLevel(nivel)


def _resposta(saida: object) -> AIMessage:
    return AIMessage(
        content=saida if isinstance(saida, str) else simplejson.dumps(saida, use_decimal=True)
    )


class AmbienteReextracao(ConfirmacaoFalsa):
    def __init__(self, monkeypatch: pytest.MonkeyPatch, saidas: list[object] | None = None) -> None:
        super().__init__(monkeypatch)
        self.banco = BancoExtracaoFalso()
        self.roteador.sessoes = self.banco
        self.producers.correcao_proposta = AsyncMock(
            side_effect=self._publicador("correcao-proposta")
        )
        self.regra = AsyncMock(return_value=RepresentacaoRegra.model_validate(REGRA))
        monkeypatch.setattr("app.graph.nodes.reextract_rule.buscar_regra", self.regra)
        self.modelo_reextracao = FakeChatModel(
            messages=iter([_resposta(s) for s in (saidas if saidas is not None else [SAIDA] * 4)])
        )
        monkeypatch.setattr(
            "app.graph.core.llm.registry.get_model", lambda _: self.modelo_reextracao
        )
        self.consumer = Consumer(CorrecaoSubmetida, "correcao-submetida", self.roteador)

    def entrada(self, texto: str | None = TEXTO) -> dict[str, Any]:
        payload = {
            "job_id": str(uuid4()),
            "regra_origem_id": str(uuid4()),
            "submissao_id": str(uuid4()),
            "competencias": ["2025-10", "2025-11"],
            "orcamento": Decimal("500000"),
            "meta_venda": Decimal("12000000"),
        }
        submissao = UUID(payload["submissao_id"])
        self.banco.transcricoes[submissao] = texto
        self.banco.respostas_antes_da_submissao[submissao] = len(
            self.banco.tabela("respostas_modelo")
        )
        return payload

    async def estado(self, payload: dict[str, Any]) -> StateSnapshot:
        thread = thread_da_correcao(UUID(payload["job_id"]), UUID(payload["submissao_id"]))
        return await build_graph(self.saver).aget_state({"configurable": {"thread_id": thread}})

    def publicadas(self, evento: str) -> list[dict[str, Any]]:
        return [payload for nome, payload in self.publicacoes if nome == evento]


def _erro_da_reextracao(payload: dict[str, Any], **extra: str) -> tuple[str, dict[str, Any]]:
    return (
        "etapa-alterada",
        {
            "job_id": payload["job_id"],
            "etapa": "extracao_parametros",
            "status": "erro",
            "regra_id": payload["regra_origem_id"],
            "submissao_id": payload["submissao_id"],
            **extra,
        },
    )


async def test_correcao_percorre_reextract_rule_e_publica_a_proposta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteReextracao(monkeypatch)
    payload = ambiente.entrada()
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert [nome for nome, _ in ambiente.publicacoes] == [
        "etapa-alterada",
        "correcao-proposta",
        "no-concluido",
    ]
    assert ambiente.publicacoes[0][1] == {
        "job_id": payload["job_id"],
        "etapa": "extracao_parametros",
        "status": "iniciada",
    }
    ambiente.regra.assert_awaited_once_with(
        ambiente.banco, UUID(payload["job_id"]), UUID(payload["regra_origem_id"])
    )
    [proposta] = ambiente.publicadas("correcao-proposta")
    assert proposta == {
        "job_id": payload["job_id"],
        "regra_origem_id": payload["regra_origem_id"],
        "submissao_id": payload["submissao_id"],
        "representacao": {
            "nucleo": {"loja": ["13"], "percentual": Decimal("0.03")},
            "especificacoes": [],
        },
        "parametros": {
            "competencias": ["2025-10", "2025-11"],
            "orcamento": Decimal("500000"),
            "meta_venda": Decimal("12000000"),
        },
    }
    oficial("correcao-proposta").validate(proposta)
    [prompt] = ambiente.banco.tabela("prompts")
    [resposta] = ambiente.banco.tabela("respostas_modelo")
    assert prompt["no"] == "extracao_parametros"
    assert prompt["job_id"] == UUID(payload["job_id"])
    assert resposta["prompt_id"] == prompt["id"]
    assert len(ambiente.modelo_reextracao.seen_messages) == 1
    [trilha] = ambiente.publicadas("no-concluido")
    assert trilha["no"] == "extracao_parametros"
    assert trilha["prompt_id"] == str(prompt["id"])
    assert trilha["regra_id"] == payload["regra_origem_id"]
    assert trilha["evento_id"] == str(
        id_do_evento_de_trilha(
            UUID(payload["job_id"]), "extracao_parametros", UUID(payload["submissao_id"])
        )
    )
    assert trilha["conclusao"]["elementos_extraidos"] == ["nucleo.loja", "nucleo.percentual"]
    estado = await ambiente.estado(payload)
    assert estado.next == ()
    assert estado.values["prompt_id"] == str(prompt["id"])
    assert estado.values["resposta_id"] == str(resposta["id"])
    assert TEXTO not in simplejson.dumps(estado.values, default=str)
    for artefato in ("representacao_regra", "prompt_enviado", "resposta_bruta", "conflitos"):
        assert artefato not in estado.values


async def test_prompt_leva_o_texto_como_dado_e_os_conflitos_recalculados(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteReextracao(monkeypatch)
    payload = ambiente.entrada()

    await ambiente.consumer.receber(mensagem(payload))

    [[enviada]] = ambiente.modelo_reextracao.seen_messages
    prompt = simplejson.loads(str(enviada.content), use_decimal=True)
    assert prompt["dados_nao_confiaveis_da_correcao"] == {"texto": TEXTO}
    assert prompt["dados_do_sistema"]["regra_atual"] == REGRA
    assert prompt["dados_do_sistema"]["conflitos"] == [
        {"elementos": ["nucleo.percentual"], "motivo": MOTIVO_DO_CONFLITO}
    ]
    assert prompt["dados_do_sistema"]["parametros_atuais"] == {
        "competencias": ["2025-10", "2025-11"],
        "orcamento": Decimal("500000"),
        "meta_venda": Decimal("12000000"),
    }
    # As publicadas, e não as do job: a correção pode levar o período a um mês que ele não tinha.
    publicadas = carregar_vocabulario()["competencias_publicadas"]
    assert prompt["dados_do_sistema"]["competencias_publicadas"] == publicadas
    assert publicadas != payload["competencias"]
    [linha] = ambiente.banco.tabela("prompts")
    assert linha["conteudo"] == enviada.content


async def test_conflitos_dos_parametros_da_versao_chegam_ao_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reextração recalcula pela mesma validação que barrou a versão (T-280)."""
    ambiente = AmbienteReextracao(monkeypatch)
    ambiente.sem_lastro.return_value = frozenset({"meta_venda"})
    payload = ambiente.entrada() | {"orcamento": Decimal("-1")}
    del payload["meta_venda"]

    await ambiente.consumer.receber(mensagem(payload))

    ambiente.sem_lastro.assert_awaited_once_with(
        ambiente.banco, UUID(payload["job_id"]), UUID(payload["regra_origem_id"])
    )
    [[enviada]] = ambiente.modelo_reextracao.seen_messages
    prompt = simplejson.loads(str(enviada.content), use_decimal=True)
    assert prompt["dados_do_sistema"]["conflitos"] == [
        {"elementos": ["nucleo.percentual"], "motivo": MOTIVO_DO_CONFLITO},
        {"elementos": ["parametros.orcamento"], "motivo": "orçamento negativo"},
        {
            "elementos": ["parametros.meta_venda"],
            "motivo": "meta de venda citada sem valor reconhecido",
        },
    ]


async def test_correcao_do_orcamento_chega_a_proposta_com_o_orcamento_novo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteReextracao(monkeypatch, [{"operacoes": [PERCENTUAL, ORCAMENTO]}])
    payload = ambiente.entrada()

    await ambiente.consumer.receber(mensagem(payload))

    [proposta] = ambiente.publicadas("correcao-proposta")
    assert proposta["parametros"] == {
        "competencias": ["2025-10", "2025-11"],
        "orcamento": 600000,
        "meta_venda": Decimal("12000000"),
    }
    oficial("correcao-proposta").validate(proposta)


@pytest.mark.parametrize("com_orcamento_e_meta", [True, False])
async def test_correcao_que_nao_fala_de_parametro_devolve_os_do_evento(
    monkeypatch: pytest.MonkeyPatch, com_orcamento_e_meta: bool
) -> None:
    ambiente = AmbienteReextracao(monkeypatch)
    payload = ambiente.entrada()
    if not com_orcamento_e_meta:
        del payload["orcamento"], payload["meta_venda"]

    await ambiente.consumer.receber(mensagem(payload))

    [proposta] = ambiente.publicadas("correcao-proposta")
    esperados = {
        campo: payload[campo]
        for campo in ("competencias", "orcamento", "meta_venda")
        if campo in payload
    }
    assert proposta["parametros"] == esperados


@pytest.mark.parametrize(
    "falha", ["sem_texto", "texto_vazio", "texto_em_branco", "regra_de_outro_job", "saida_invalida"]
)
async def test_falha_permanente_publica_erro_com_a_versao_e_a_correcao_e_rejeita(
    monkeypatch: pytest.MonkeyPatch, falha: str
) -> None:
    textos = {"sem_texto": None, "texto_vazio": "", "texto_em_branco": " \n\t"}
    saidas: list[object] = ["RESPOSTA_PRIVADA_INVALIDA"] if falha == "saida_invalida" else [SAIDA]
    ambiente = AmbienteReextracao(monkeypatch, saidas)
    payload = ambiente.entrada(textos.get(falha, TEXTO))
    if falha == "regra_de_outro_job":
        ambiente.regra.side_effect = RegraInvalidaError("Rule not found for this job")
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    recebida.nack.assert_not_awaited()
    recebida.ack.assert_not_awaited()
    assert ambiente.publicacoes[-1] == _erro_da_reextracao(payload)
    assert ambiente.publicadas("correcao-proposta") == []
    assert ambiente.publicadas("no-concluido") == []
    assert ambiente.banco.tabela("prompts") == []
    chamadas = 1 if falha == "saida_invalida" else 0
    assert len(ambiente.modelo_reextracao.seen_messages) == chamadas


async def test_correcao_sem_competencias_falha_na_etapa_da_reextracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mensagem anterior ao campo não tem como preservar o período do job na proposta."""
    ambiente = AmbienteReextracao(monkeypatch)
    payload = ambiente.entrada()
    del payload["competencias"]
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    assert ambiente.publicacoes[-1] == _erro_da_reextracao(payload)
    assert ambiente.modelo_reextracao.seen_messages == []
    ambiente.regra.assert_not_awaited()


async def test_falha_transitoria_do_provedor_reenfileira_sem_publicar_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteReextracao(monkeypatch)
    payload = ambiente.entrada()
    original = FakeChatModel.ainvoke
    monkeypatch.setattr(
        FakeChatModel, "ainvoke", AsyncMock(side_effect=RuntimeError("SEGREDO_DO_PROVEDOR"))
    )
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.nack.assert_awaited_once_with(requeue=True)
    recebida.reject.assert_not_awaited()
    assert all(p.get("status") != "erro" for _, p in ambiente.publicacoes)
    assert ambiente.publicadas("correcao-proposta") == []
    monkeypatch.setattr(FakeChatModel, "ainvoke", original)
    repetida = mensagem(payload)
    await ambiente.consumer.receber(repetida)
    repetida.ack.assert_awaited_once_with()
    assert len(ambiente.publicadas("correcao-proposta")) == 1


async def test_provedor_indisponivel_na_janela_inteira_falha_com_causa_e_referencias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relogio = Relogio()
    monkeypatch.setattr(disponibilidade, "_dormir", relogio.dormir)
    monkeypatch.setattr(disponibilidade, "_agora", relogio.agora)
    monkeypatch.setattr(
        "app.repositorio.encerramentos.foi_encerrado", AsyncMock(return_value=False)
    )
    ambiente = AmbienteReextracao(monkeypatch)
    payload = ambiente.entrada()
    servidor = ServerError(503, {"error": {"message": "SEGREDO", "status": "UNAVAILABLE"}})
    monkeypatch.setattr(FakeChatModel, "ainvoke", AsyncMock(side_effect=servidor))
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    etapas = ambiente.publicadas("etapa-alterada")
    assert [(p["status"], p["etapa"]) for p in etapas] == [
        ("iniciada", "extracao_parametros"),
        ("aguardando_provedor", "extracao_parametros"),
        ("erro", "extracao_parametros"),
    ]
    assert ambiente.publicacoes[-1] == _erro_da_reextracao(payload, causa="provedor_indisponivel")


async def test_reentrega_depois_do_fim_nao_chama_o_modelo_nem_publica(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    ambiente = AmbienteReextracao(monkeypatch)
    payload = ambiente.entrada()
    await ambiente.consumer.receber(mensagem(payload))
    publicacoes = list(ambiente.publicacoes)
    linhas = {nome: ambiente.banco.tabela(nome) for nome in ambiente.banco.linhas}
    antes = (await cliente.get("/metrics")).text
    repetida = mensagem(payload)

    await ambiente.consumer.receber(repetida)

    repetida.ack.assert_awaited_once_with()
    assert ambiente.publicacoes == publicacoes
    assert {nome: ambiente.banco.tabela(nome) for nome in linhas} == linhas
    assert len(ambiente.modelo_reextracao.seen_messages) == 1
    depois = (await cliente.get("/metrics")).text
    rotulos = {"job_name": "reextract_rule"}
    assert amostra(depois, "job_runs_total", rotulos) == amostra(antes, "job_runs_total", rotulos)
    [ignorada] = [log for log in logs if log["message"].startswith("correção já reextraída")]
    assert ignorada["job_id"] == payload["job_id"]
    assert ignorada["extra"] == {
        "tipo_mensagem": "correcao-submetida",
        "regra_id": payload["regra_origem_id"],
        "submissao_id": payload["submissao_id"],
    }


@pytest.mark.parametrize("falha_em", ["correcao_proposta", "no_concluido"])
async def test_reexecucao_depois_de_gravar_a_resposta_a_reaplica_sem_chamar_o_modelo(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]], falha_em: str
) -> None:
    """Uma segunda chamada poderia trazer outra proposta, e a trilha apontaria um prompt que não
    gerou a versão que a api aplicou."""
    outra = {"operacoes": [PERCENTUAL, ORCAMENTO]}
    ambiente = AmbienteReextracao(monkeypatch, [SAIDA, outra])
    payload = ambiente.entrada()
    produtor = getattr(ambiente.producers, falha_em)
    original = produtor.side_effect
    produtor.side_effect = ConnectionError("BROKER_PRIVADO")
    primeira = mensagem(payload)
    await ambiente.consumer.receber(primeira)
    primeira.nack.assert_awaited_once_with(requeue=True)
    produtor.side_effect = original
    segunda = mensagem(payload)

    await ambiente.consumer.receber(segunda)

    segunda.ack.assert_awaited_once_with()
    assert len(ambiente.modelo_reextracao.seen_messages) == 1
    [prompt] = ambiente.banco.tabela("prompts")
    assert len(ambiente.banco.tabela("respostas_modelo")) == 1
    propostas = ambiente.publicadas("correcao-proposta")
    assert propostas[-1]["parametros"]["orcamento"] == payload["orcamento"]
    assert all(proposta == propostas[0] for proposta in propostas)
    [trilha] = ambiente.publicadas("no-concluido")
    assert trilha["prompt_id"] == str(prompt["id"])
    desfechos = [
        log["extra"]["resposta_reutilizada"]
        for log in logs
        if log["message"] in ("reextraction failed", "reextraction finished")
    ]
    assert desfechos == [False, True]


async def test_correcao_nova_com_o_mesmo_texto_chama_o_modelo_de_novo(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    """A resposta de uma correção anterior não serve a outra, mesmo com o prompt igual."""
    outra = {"operacoes": [PERCENTUAL, ORCAMENTO]}
    ambiente = AmbienteReextracao(monkeypatch, [SAIDA, outra])
    primeira = ambiente.entrada()
    await ambiente.consumer.receber(mensagem(primeira))
    segunda = primeira | {"submissao_id": str(uuid4())}
    ambiente.banco.transcricoes[UUID(segunda["submissao_id"])] = TEXTO
    ambiente.banco.respostas_antes_da_submissao[UUID(segunda["submissao_id"])] = 1

    await ambiente.consumer.receber(mensagem(segunda))

    assert len(ambiente.modelo_reextracao.seen_messages) == 2
    primeira_proposta, segunda_proposta = ambiente.publicadas("correcao-proposta")
    assert primeira_proposta["parametros"]["orcamento"] == primeira["orcamento"]
    assert segunda_proposta["parametros"]["orcamento"] == 600000
    primeira_trilha, segunda_trilha = ambiente.publicadas("no-concluido")
    assert primeira_trilha["prompt_id"] != segunda_trilha["prompt_id"]
    assert [
        log["extra"]["resposta_reutilizada"]
        for log in logs
        if log["message"] == "reextraction finished"
    ] == [False, False]


async def test_reentrega_depois_de_falha_na_trilha_repete_a_proposta_sem_duplicar_artefatos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteReextracao(monkeypatch)
    payload = ambiente.entrada()
    original = ambiente.producers.no_concluido.side_effect
    ambiente.producers.no_concluido.side_effect = ConnectionError("BROKER_PRIVADO")
    primeira = mensagem(payload)
    await ambiente.consumer.receber(primeira)
    primeira.nack.assert_awaited_once_with(requeue=True)
    tentativa = ambiente.producers.no_concluido.await_args.args[0]
    ambiente.producers.no_concluido.side_effect = original
    segunda = mensagem(payload)

    await ambiente.consumer.receber(segunda)

    segunda.ack.assert_awaited_once_with()
    # A api trata a proposta repetida como duplicada (T-217); a trilha usa o mesmo evento.
    assert len(ambiente.publicadas("correcao-proposta")) == 2
    [trilha] = ambiente.publicadas("no-concluido")
    assert trilha["evento_id"] == str(tentativa.evento_id)
    assert len(ambiente.banco.tabela("prompts")) == 1
    assert len(ambiente.banco.tabela("respostas_modelo")) == 1


@pytest.mark.parametrize("encerramento", list(EstadoDoEncerramento))
async def test_correcao_de_job_encerrado_e_confirmada_sem_abrir_ciclo(
    monkeypatch: pytest.MonkeyPatch, encerramento: EstadoDoEncerramento
) -> None:
    ambiente = AmbienteReextracao(monkeypatch)
    ambiente.limpeza.encerramento = encerramento
    payload = ambiente.entrada()
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    recebida.reject.assert_not_awaited()
    recebida.nack.assert_not_awaited()
    assert ambiente.publicacoes == []
    assert (await ambiente.estado(payload)).values == {}
    assert ambiente.modelo_reextracao.seen_messages == []


@pytest.mark.parametrize(
    "falha",
    [
        None,
        "entrada_invalida",
        "regra_indisponivel",
        "transcricao_indisponivel",
        "saida_invalida",
        "provedor",
        "persistencia",
        "publicacao",
        "cancelamento",
    ],
)
async def test_logs_e_metricas_pelo_caminho_real_em_sucesso_e_falha(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
    falha: str | None,
) -> None:
    saida = {
        "operacoes": [
            PERCENTUAL,
            # Sem lastro no texto: a operação vira diagnóstico.
            {
                "tipo": "definir_nucleo",
                "trecho": "3%",
                "campo": "marca",
                "valor": [{"valor": "10", "trecho": "marca 10"}],
            },
            # Nenhum construto habilitado: o elemento entra como genérico, rebaixado.
            {
                "tipo": "adicionar_elemento",
                "trecho": "orçamento passa a ser R$ 600 mil",
                "elemento": {
                    "construto_pretendido": "FORMA_PRIVADA",
                    "descricao": "PARAFRASE_PRIVADA",
                    "trecho": "orçamento passa a ser R$ 600 mil",
                },
            },
        ]
    }
    ambiente = AmbienteReextracao(monkeypatch, [saida])
    payload = ambiente.entrada()
    aguardando = asyncio.Event()
    if falha == "entrada_invalida":
        del payload["competencias"]
    elif falha == "regra_indisponivel":
        ambiente.regra.side_effect = RegraInvalidaError("Rule not found for this job")
    elif falha == "transcricao_indisponivel":
        ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = ""
    elif falha == "saida_invalida":
        ambiente.modelo_reextracao.messages = iter([_resposta("RESPOSTA_PRIVADA_INVALIDA")])
    elif falha in ("provedor", "cancelamento"):

        async def falhar(*args: Any, **kwargs: Any) -> Any:
            if falha == "cancelamento":
                aguardando.set()
                await asyncio.Event().wait()
            raise RuntimeError("RESPOSTA_PRIVADA_DO_PROVEDOR")

        monkeypatch.setattr(FakeChatModel, "ainvoke", falhar)
    elif falha == "persistencia":
        ambiente.banco.falhar_em = ("prompts",)
    elif falha == "publicacao":
        ambiente.producers.correcao_proposta.side_effect = RuntimeError("BROKER_PRIVADO")
    antes = (await cliente.get("/metrics")).text
    recebida = mensagem(payload)

    if falha == "cancelamento":
        tarefa = asyncio.create_task(ambiente.consumer.receber(recebida))
        await asyncio.wait_for(aguardando.wait(), timeout=5)
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa
    else:
        await ambiente.consumer.receber(recebida)

    depois = (await cliente.get("/metrics")).text
    rotulos = {"job_name": "reextract_rule"}
    for nome, esperado in (
        ("job_runs_total", 1),
        ("job_failures_total", 1 if falha else 0),
        ("job_duration_seconds_count", 1),
    ):
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == esperado
    for nome, label, valor, quantidade in (
        ("codegen_extracao_elementos_total", "construto", "nucleo", 2),
        ("codegen_extracao_elementos_total", "construto", "generico", 1),
        ("codegen_extracao_rebaixamentos_total", "motivo", "valor_sem_lastro", 1),
        ("codegen_extracao_rebaixamentos_total", "motivo", "construto_nao_habilitado", 1),
    ):
        delta = amostra(depois, nome, {label: valor}) - amostra(antes, nome, {label: valor})
        assert delta == (0 if falha else quantidade)
    for classe in (
        "entrada_invalida",
        "regra_indisponivel",
        "transcricao_indisponivel",
        "saida_invalida",
        "provedor",
        "persistencia",
        "publicacao",
        "cancelamento",
    ):
        rotulo = {"classe": classe}
        delta = amostra(depois, "codegen_extracao_falhas_total", rotulo) - amostra(
            antes, "codegen_extracao_falhas_total", rotulo
        )
        assert delta == int(classe == falha)
    validador = Draft202012Validator(
        simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes()),
        format_checker=FormatChecker(),
    )
    do_no = [log for log in logs if log.get("no") == "extracao_parametros"]
    assert [log["message"] for log in do_no] == [
        "reextraction started",
        "reextraction failed" if falha else "reextraction finished",
    ]
    referencias = {
        "regra_id": payload["regra_origem_id"],
        "submissao_id": payload["submissao_id"],
    }
    assert do_no[0]["extra"] == referencias
    if falha:
        assert do_no[-1]["extra"]["classe"] == falha
    else:
        [prompt] = ambiente.banco.tabela("prompts")
        assert do_no[-1]["extra"] == {
            **referencias,
            "prompt_id": str(prompt["id"]),
            "resposta_reutilizada": False,
            "elementos_por_construto": {"generico": 1, "nucleo": 2},
            "rebaixamentos_por_motivo": {"valor_sem_lastro": 1, "construto_nao_habilitado": 1},
        }
    for log in logs:
        validador.validate(log)
        assert log["job_id"] == payload["job_id"]
    serializados = simplejson.dumps(logs)
    for privado in (
        TEXTO,
        "CORRECAO_PRIVADA",
        MOTIVO_DO_CONFLITO,
        "PARAFRASE_PRIVADA",
        "FORMA_PRIVADA",
        "RESPOSTA_PRIVADA",
        "BROKER_PRIVADO",
        "representacao",
        "operacoes",
    ):
        assert privado not in serializados
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None


async def test_correlacao_e_restaurada_entre_duas_correcoes(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    ambiente = AmbienteReextracao(monkeypatch)
    primeira, segunda = ambiente.entrada(""), ambiente.entrada()
    token_job = job_id_ctx.set("contexto_anterior")
    token_no = no_ctx.set("decisao")
    try:
        await ambiente.consumer.receber(mensagem(primeira))
        assert job_id_ctx.get() == "contexto_anterior"
        assert no_ctx.get() == "decisao"
        await ambiente.consumer.receber(mensagem(segunda))
        assert job_id_ctx.get() == "contexto_anterior"
        assert no_ctx.get() == "decisao"
    finally:
        no_ctx.reset(token_no)
        job_id_ctx.reset(token_job)
    assert [
        (log["job_id"], log["message"]) for log in logs if log.get("no") == "extracao_parametros"
    ] == [
        (primeira["job_id"], "reextraction started"),
        (primeira["job_id"], "reextraction failed"),
        (segunda["job_id"], "reextraction started"),
        (segunda["job_id"], "reextraction finished"),
    ]


def _adicionar_rodada(
    ambiente: AmbienteReextracao,
    job_id: UUID,
    anterior: UUID | None,
    texto: str,
    indice: int,
    *,
    submissao: UUID | None = None,
) -> UUID:
    rodada = uuid4()
    submissao = submissao or uuid4()
    ambiente.banco.rodadas_correcao.append(
        {
            "id": rodada,
            "job_id": job_id,
            "rodada_anterior_id": anterior,
            "submissao_correcao_id": submissao,
            "conflitos": [{"elementos": [f"elem.{indice}"], "motivo": f"motivo {indice}"}],
        }
    )
    ambiente.banco.transcricoes[submissao] = texto
    return rodada


async def test_terceira_correcao_repassa_historico_apenas_no_compartimento_nao_confiavel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteReextracao(monkeypatch)
    payload = ambiente.entrada()
    job = UUID(payload["job_id"])
    anterior = _adicionar_rodada(ambiente, job, None, "PRIVADO_ANTERIOR_1", 1)
    anterior = _adicionar_rodada(ambiente, job, anterior, "PRIVADO_ANTERIOR_2", 2)
    _adicionar_rodada(ambiente, job, anterior, TEXTO, 3, submissao=UUID(payload["submissao_id"]))

    await ambiente.consumer.receber(mensagem(payload))

    [[chamada]] = ambiente.modelo_reextracao.seen_messages
    prompt = simplejson.loads(str(chamada.content))
    assert prompt["dados_nao_confiaveis_da_correcao"] == {
        "texto": TEXTO,
        "historico": [
            {
                "texto": "PRIVADO_ANTERIOR_1",
                "conflitos": [{"elementos": ["elem.1"], "motivo": "motivo 1"}],
            },
            {
                "texto": "PRIVADO_ANTERIOR_2",
                "conflitos": [{"elementos": ["elem.2"], "motivo": "motivo 2"}],
            },
        ],
    }
    for compartimento in ("instrucoes_fixas_do_sistema", "dados_do_sistema"):
        assert "PRIVADO_ANTERIOR" not in simplejson.dumps(prompt[compartimento])
    assert "PRIVADO_ANTERIOR" not in simplejson.dumps((await ambiente.estado(payload)).values)
    assert ambiente.publicadas("correcao-proposta")


async def test_historico_nao_fornece_lastro_para_orcamento_novo_no_grafo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operacao = {
        "tipo": "definir_parametro",
        "trecho": "Mantenha a regra",
        "campo": "orcamento",
        "valor": {"valor": 700000, "trecho": "R$ 700 mil"},
    }
    ambiente = AmbienteReextracao(monkeypatch, [{"operacoes": [operacao]}])
    payload = ambiente.entrada("Mantenha a regra atual.")
    job = UUID(payload["job_id"])
    anterior = _adicionar_rodada(ambiente, job, None, "Histórico: R$ 700 mil.", 1)
    _adicionar_rodada(
        ambiente,
        job,
        anterior,
        "Mantenha a regra atual.",
        2,
        submissao=UUID(payload["submissao_id"]),
    )

    await ambiente.consumer.receber(mensagem(payload))

    [proposta] = ambiente.publicadas("correcao-proposta")
    assert proposta["parametros"]["orcamento"] == Decimal("500000")


async def test_metricas_de_operacao_sem_trecho_e_valor_sem_lastro_apos_grafo(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
) -> None:
    saida = {
        "operacoes": [
            {"tipo": "remover_parametro", "campo": "orcamento"},
            {
                "tipo": "definir_parametro",
                "trecho": "R$ 600 mil",
                "campo": "orcamento",
                "valor": {"valor": 700000, "trecho": "R$ 600 mil"},
            },
        ]
    }
    ambiente = AmbienteReextracao(monkeypatch, [saida])
    payload = ambiente.entrada()
    antes = (await cliente.get("/metrics")).text

    await ambiente.consumer.receber(mensagem(payload))

    depois = (await cliente.get("/metrics")).text
    [proposta] = ambiente.publicadas("correcao-proposta")
    assert proposta["parametros"]["orcamento"] == Decimal("500000")
    for motivo in ("operacao_sem_trecho", "valor_sem_lastro"):
        rotulo = {"motivo": motivo}
        assert (
            amostra(depois, "codegen_extracao_rebaixamentos_total", rotulo)
            - amostra(antes, "codegen_extracao_rebaixamentos_total", rotulo)
            == 1
        )
    desfecho = [log for log in logs if log["message"] == "reextraction finished"]
    assert len(desfecho) == 1
    assert desfecho[0]["extra"]["rebaixamentos_por_motivo"] == {
        "operacao_sem_trecho": 1,
        "valor_sem_lastro": 1,
    }
    assert TEXTO not in simplejson.dumps(logs)
