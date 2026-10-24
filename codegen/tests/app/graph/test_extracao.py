import asyncio
import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import simplejson
from httpx import AsyncClient, ConnectError, ReadTimeout
from jsonschema import Draft202012Validator, FormatChecker
from langchain_core.messages import AIMessage
from prometheus_client.parser import text_string_to_metric_families

from app.contratos.mensagens import RegraSubmetida
from app.core.logger import FormatadorJson, ManipuladorFilaContexto, job_id_ctx, no_ctx
from app.mensageria.consumers import Consumer
from tests.app.confirmacao_falsa import ConfirmacaoFalsa, mensagem
from tests.app.extracao_falsa import BancoExtracaoFalso
from tests.app.graph.conftest import FakeChatModel
from tests.app.test_mensageria import CONTRATOS

TEXTO = (
    "Pague 2,5% na loja 13. orçamento de R$ 500 mil; "
    "meta de 12 milhões entre setembro e novembro de 2025. REGRA_PRIVADA"
)
NUCLEO = {"percentual": Decimal("0.025"), "loja": ["13"]}
NUCLEO_RASCUNHO = {
    "percentual": {"valor": Decimal("0.025"), "trecho": "2,5%"},
    "loja": [{"valor": "13", "trecho": "loja 13"}],
}
SAIDA = {"nucleo": NUCLEO_RASCUNHO, "elementos": [], "parametros": {}}


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


class AmbienteExtracao(ConfirmacaoFalsa):
    def __init__(self, monkeypatch: pytest.MonkeyPatch, saidas: list[Any] | None = None) -> None:
        super().__init__(monkeypatch)
        self.banco = BancoExtracaoFalso()
        self.roteador.sessoes = self.banco
        self.producers.regra_extraida = AsyncMock(side_effect=self._publicador("regra-extraida"))
        self.modelo_extracao = FakeChatModel(
            messages=iter(
                [
                    AIMessage(
                        content=s if isinstance(s, str) else simplejson.dumps(s, use_decimal=True)
                    )
                    for s in (saidas if saidas is not None else [SAIDA] * 4)
                ]
            )
        )
        monkeypatch.setattr("app.graph.core.llm.registry.get_model", lambda _: self.modelo_extracao)
        self.consumer = Consumer(RegraSubmetida, "regra-submetida", self.roteador)

    def entrada(self, origem: str = "texto") -> dict[str, Any]:
        payload = {
            "job_id": str(uuid4()),
            "submissao_id": str(uuid4()),
            "origem": origem,
            "competencias": ["2025-11"],
            "orcamento": Decimal("500"),
        }
        self.banco.transcricoes[UUID(payload["submissao_id"])] = TEXTO
        return payload


@pytest.mark.parametrize("origem", ["voz", "texto"])
@pytest.mark.parametrize("trecho_percentual", ["2,5%", "2,5 por cento"])
async def test_extracao_persiste_publica_ids_e_termina_ciclo(
    monkeypatch: pytest.MonkeyPatch,
    origem: str,
    trecho_percentual: str,
) -> None:
    saida = {
        **SAIDA,
        "nucleo": {
            **NUCLEO_RASCUNHO,
            "percentual": {"valor": Decimal("0.025"), "trecho": trecho_percentual},
        },
    }
    ambiente = AmbienteExtracao(monkeypatch, [saida])
    payload = ambiente.entrada(origem)
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = TEXTO.replace(
        "2,5%", trecho_percentual
    )
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert [nome for nome, _ in ambiente.publicacoes] == [
        "etapa-alterada",
        "regra-extraida",
        "no-concluido",
    ]
    [prompt] = ambiente.banco.tabela("prompts")
    [resposta] = ambiente.banco.tabela("respostas_modelo")
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    assert prompt["no"] == "extracao_parametros"
    assert resposta["prompt_id"] == prompt["id"]
    assert simplejson.loads(extracao["representacao"], use_decimal=True) == {
        "nucleo": NUCLEO,
        "especificacoes": [],
    }
    assert simplejson.loads(extracao["parametros"], use_decimal=True) == {}
    assert ambiente.publicacoes[1][1] == {
        "job_id": payload["job_id"],
        "submissao_id": payload["submissao_id"],
        "extracao_id": str(extracao["id"]),
    }
    trilha = ambiente.publicacoes[2][1]
    assert trilha["prompt_id"] == str(prompt["id"])
    assert trilha["no"] == "extracao_parametros"
    assert "regra_id" not in trilha
    assert trilha["conclusao"]["elementos_extraidos"] == ["nucleo.percentual", "nucleo.loja"]
    estado = await ambiente.estado(payload)
    assert estado.next == ()
    assert estado.values["prompt_id"] == str(prompt["id"])
    assert estado.values["resposta_id"] == str(resposta["id"])
    assert estado.values["submissao_id"] == payload["submissao_id"]
    for artefato in ("representacao_regra", "prompt_enviado", "resposta_bruta", "messages"):
        assert artefato not in estado.values or not estado.values[artefato]


async def test_parametros_ditos_no_texto_sao_gravados_na_extracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saida = {
        "nucleo": NUCLEO_RASCUNHO,
        "elementos": [],
        "parametros": {
            "orcamento": {"valor": Decimal("500000"), "trecho": "orçamento de R$ 500 mil"},
            "meta_venda": {"valor": Decimal("12000000"), "trecho": "meta de 12 milhões"},
            "competencias": {
                "valor": ["2025-09", "2025-10", "2025-11"],
                "trecho": "entre setembro e novembro de 2025",
            },
        },
    }
    ambiente = AmbienteExtracao(monkeypatch, [saida])
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(extracao["parametros"], use_decimal=True) == {
        "orcamento": Decimal("500000"),
        "meta_venda": Decimal("12000000"),
        "competencias": ["2025-09", "2025-10", "2025-11"],
    }
    # Nunca faz parte da regra: fora de nucleo/especificacoes e do evento regra-extraida.
    assert "parametros" not in simplejson.loads(extracao["representacao"], use_decimal=True)
    assert set(ambiente.publicacoes[1][1]) == {"job_id", "submissao_id", "extracao_id"}


@pytest.mark.parametrize("texto", [None, "", " \n\t"])
async def test_transcricao_indisponivel_rejeita_sem_modelo(
    monkeypatch: pytest.MonkeyPatch,
    texto: str | None,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = texto
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    assert ambiente.modelo_extracao.seen_messages == []
    assert ambiente.publicacoes[-1][1]["etapa"] == "extracao_parametros"
    assert ambiente.publicacoes[-1][1]["status"] == "erro"
    assert ambiente.banco.tabela("prompts") == []


async def test_saida_invalida_encerra_job_sem_publicar_extracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch, ["RESPOSTA_PRIVADA_INVALIDA"])
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.reject.assert_awaited_once_with(requeue=False)
    assert len(ambiente.modelo_extracao.seen_messages) == 1
    ambiente.producers.regra_extraida.assert_not_awaited()
    assert ambiente.banco.tabela("prompts") == []
    assert ambiente.publicacoes[-1][1]["status"] == "erro"


async def test_falha_transitoria_reentrega_sem_erro_do_job(monkeypatch: pytest.MonkeyPatch) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada()
    ambiente.banco.falhar_em = ("extracoes_regras",)
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.nack.assert_awaited_once_with(requeue=True)
    assert ambiente.banco.tabela("prompts") == []
    assert all(p.get("status") != "erro" for _, p in ambiente.publicacoes)
    ambiente.banco.falhar_em = ()
    repetida = mensagem(payload)
    await ambiente.consumer.receber(repetida)
    repetida.ack.assert_awaited_once_with()


async def test_reentrega_apos_publicacao_reusa_artefato_e_nao_duplica_trilha(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada()
    antes = (await cliente.get("/metrics")).text
    original = ambiente.producers.no_concluido.side_effect
    ambiente.producers.no_concluido.side_effect = RuntimeError("BROKER_PRIVADO")
    primeira = mensagem(payload)
    await ambiente.consumer.receber(primeira)
    primeira.nack.assert_awaited_once_with(requeue=True)
    primeiro_evento = ambiente.producers.no_concluido.await_args.args[0]
    segunda = mensagem(payload)
    await ambiente.consumer.receber(segunda)
    segunda.nack.assert_awaited_once_with(requeue=True)

    ambiente.producers.no_concluido.side_effect = original
    terceira = mensagem(payload)
    await ambiente.consumer.receber(terceira)
    terceira.ack.assert_awaited_once_with()
    assert len(ambiente.modelo_extracao.seen_messages) == 1
    assert all(
        len(ambiente.banco.tabela(t)) == 1
        for t in ("prompts", "respostas_modelo", "extracoes_regras")
    )
    assert ambiente.producers.no_concluido.await_args.args[0].evento_id == primeiro_evento.evento_id
    desfechos = [
        log for log in logs if log["message"] in ("extraction failed", "extraction finished")
    ]
    assert [log["extra"]["extracao_reutilizada"] for log in desfechos] == [False, True, True]
    depois = (await cliente.get("/metrics")).text
    for nome, delta in (
        ("job_runs_total", 3),
        ("job_failures_total", 2),
        ("job_duration_seconds_count", 3),
    ):
        rotulos = {"job_name": "extract_rule"}
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == delta
    assert amostra(depois, "codegen_extracao_elementos_total", {"construto": "nucleo"}) - amostra(
        antes, "codegen_extracao_elementos_total", {"construto": "nucleo"}
    ) == len(NUCLEO)
    anteriores = list(ambiente.publicacoes)
    logs_anteriores = list(logs)
    quarta = mensagem(payload)
    await ambiente.consumer.receber(quarta)
    quarta.ack.assert_awaited_once_with()
    assert ambiente.publicacoes == anteriores
    assert logs == logs_anteriores
    posteriores = (await cliente.get("/metrics")).text
    assert amostra(posteriores, "job_runs_total", rotulos) == amostra(
        depois, "job_runs_total", rotulos
    )
    assert len(ambiente.modelo_extracao.seen_messages) == 1


async def test_bonus_fixo_extraido_conta_o_construto_e_nao_vaza_a_matricula(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
) -> None:
    texto = "Conceder bônus fixo de R$ 500 para a matrícula MATRIC-422"
    bonus = {
        "construto_pretendido": "bonus_fixo",
        "descricao": texto,
        "trecho": texto,
        "tipo_alvo": "lista",
        "matriculas": ["MATRIC-422"],
        "valor": {"valor": Decimal("500"), "trecho": "R$ 500"},
    }
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": {}, "elementos": [bonus], "parametros": {}}]
    )
    payload = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = texto
    rotulos = {"construto": "bonus_fixo"}
    antes = (await cliente.get("/metrics")).text

    recebida = mensagem(payload)
    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(extracao["representacao"], use_decimal=True)["especificacoes"] == [
        {
            "ref": "elem.1",
            "construto": "bonus_fixo",
            "alvo": {"tipo": "lista", "valor": ["MATRIC-422"]},
            "valor": Decimal("500"),
        }
    ]
    depois = (await cliente.get("/metrics")).text
    nome = "codegen_extracao_elementos_total"
    assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == 1
    assert ambiente.publicacoes[-1][1]["conclusao"]["elementos_extraidos"] == ["elem.1"]
    assert "MATRIC-422" not in simplejson.dumps(logs)


@pytest.mark.parametrize(
    ("efeito_no_texto", "evidencia"),
    [
        ("+1% no percentual", "+1%"),
        ("acréscimo percentual de 0,01 em fração", "acréscimo percentual de 0,01 em fração"),
        ("0,01 (fração) no percentual", "0,01 (fração) no percentual"),
        ("acréscimo em fração de 0.01", "fração de 0.01"),
        ("0,01 como fração do percentual", "0,01 como fração do percentual"),
        ("percentual em fração decimal de 0,01", "percentual em fração decimal de 0,01"),
    ],
)
async def test_janela_datas_extraida_conta_o_construto(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
    efeito_no_texto: str,
    evidencia: str,
) -> None:
    texto = f"Vendas de 24/11 a 30/11 terão {efeito_no_texto}"
    janela = {
        "construto_pretendido": "janela_datas",
        "descricao": texto,
        "trecho": texto,
        "data_inicial": "2025-11-24",
        "data_final": "2025-11-30",
        "efeito": {
            "tipo": "acrescimo_pct",
            "valor": {"valor": Decimal("0.01"), "trecho": evidencia},
        },
    }
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": {}, "elementos": [janela], "parametros": {}}]
    )
    payload = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = texto
    rotulos = {"construto": "janela_datas"}
    antes = (await cliente.get("/metrics")).text

    recebida = mensagem(payload)
    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    [elemento] = simplejson.loads(extracao["representacao"], use_decimal=True)["especificacoes"]
    assert elemento["construto"] == "janela_datas"
    assert (elemento["data_inicial"], elemento["data_final"]) == ("2025-11-24", "2025-11-30")
    assert elemento["efeito"] == {"tipo": "acrescimo_pct", "valor": Decimal("0.01")}
    assert simplejson.loads(extracao["rebaixamentos"]) == []
    depois = (await cliente.get("/metrics")).text
    nome = "codegen_extracao_elementos_total"
    assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == 1
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    validador = Draft202012Validator(schema, format_checker=FormatChecker())
    do_no = [log for log in logs if log.get("no") == "extracao_parametros"]
    assert [log["message"] for log in do_no] == ["extraction started", "extraction finished"]
    assert do_no[-1]["extra"]["elementos_por_construto"]["janela_datas"] == 1
    assert do_no[-1]["extra"]["rebaixamentos_por_motivo"] == {}
    for log in logs:
        validador.validate(log)
        assert log["job_id"] == payload["job_id"]
    assert texto not in simplejson.dumps(logs)
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None


@pytest.mark.parametrize(
    ("trecho", "evidencia", "valor", "data_final"),
    [
        (
            "Vendas de 1/11 a 30/11 terão +1%",
            "Vendas de 1/11 a 30/11 terão +1%",
            "1",
            "2025-11-30",
        ),
        ("Vendas de 1/11 a 30/11 terão +1%", "+3%", "0.03", "2025-11-30"),
        ("Vendas de 1/11 a 31/11 terão +1%", "+1%", "0.01", "2025-11-01"),
        (
            "Vendas de 1/11 a 30/11 terão uma fração da comissão",
            "uma fração da comissão",
            "0.37",
            "2025-11-30",
        ),
        (
            "Vendas de 1/11 a 30/11 terão fração de 0,01 reais",
            "fração de 0,01 reais",
            "0.01",
            "2025-11-30",
        ),
        (
            "Vendas de 1/11 a 30/11 terão fração de 0,01 reais",
            "fração de 0,01",
            "0.01",
            "2025-11-30",
        ),
    ],
    ids=[
        "percentual_ancorado_no_dia",
        "efeito_de_outra_janela",
        "data_invalida",
        "fracao_sem_proporcao",
        "fracao_em_reais",
        "evidencia_sem_unidade_monetaria",
    ],
)
async def test_janela_sem_lastro_persiste_rebaixamento_e_emite_logs_e_metricas(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
    trecho: str,
    evidencia: str,
    valor: str,
    data_final: str,
) -> None:
    texto = f"{trecho}. De 01/12 a 05/12 haverá +3%. REGRA_PRIVADA_JANELA"
    janela = {
        "construto_pretendido": "janela_datas",
        "descricao": trecho,
        "trecho": trecho,
        "data_inicial": "2025-11-01",
        "data_final": data_final,
        "efeito": {
            "tipo": "acrescimo_pct",
            "valor": {"valor": Decimal(valor), "trecho": evidencia},
        },
    }
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": {}, "elementos": [janela], "parametros": {}}]
    )
    payload = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = texto
    antes = (await cliente.get("/metrics")).text
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(extracao["representacao"])["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": trecho}
    ]
    assert simplejson.loads(extracao["rebaixamentos"]) == [
        {
            "ref": "elem.1",
            "construto_pretendido": "janela_datas",
            "motivo": "valor_sem_lastro",
        }
    ]
    depois = (await cliente.get("/metrics")).text
    for nome, rotulos, delta in (
        ("codegen_extracao_elementos_total", {"construto": "generico"}, 1),
        ("codegen_extracao_elementos_total", {"construto": "janela_datas"}, 0),
        ("codegen_extracao_rebaixamentos_total", {"motivo": "valor_sem_lastro"}, 1),
        ("job_runs_total", {"job_name": "extract_rule"}, 1),
        ("job_failures_total", {"job_name": "extract_rule"}, 0),
        ("job_duration_seconds_count", {"job_name": "extract_rule"}, 1),
    ):
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == delta
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    validador = Draft202012Validator(schema, format_checker=FormatChecker())
    do_no = [log for log in logs if log.get("no") == "extracao_parametros"]
    assert [log["message"] for log in do_no] == ["extraction started", "extraction finished"]
    assert do_no[-1]["extra"]["rebaixamentos_por_motivo"] == {"valor_sem_lastro": 1}
    for log in logs:
        validador.validate(log)
        assert log["job_id"] == payload["job_id"]
    for privado in (trecho, texto, "REGRA_PRIVADA_JANELA", "representacao"):
        assert privado not in simplejson.dumps(logs)
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None


async def test_faixas_de_valor_extraidas_contam_o_construto_por_elemento(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
) -> None:
    texto = "40000 até 50000, R$ 3500; acima de 50001, R$ 4000"

    def faixa(trecho: str, inferior: str, bonus: str, superior: str | None) -> dict[str, Any]:
        elemento: dict[str, Any] = {
            "construto_pretendido": "faixa_valor",
            "descricao": trecho,
            "trecho": trecho,
            "limite_inferior": {"valor": Decimal(inferior), "trecho": inferior},
            "faixa_aberta": superior is None,
            "efeito": {
                "tipo": "bonus_fixo",
                "valor": {"valor": Decimal(bonus), "trecho": f"R$ {bonus}"},
            },
        }
        if superior is not None:
            elemento["limite_superior"] = {"valor": Decimal(superior), "trecho": superior}
        return elemento

    elementos = [
        faixa("40000 até 50000, R$ 3500", "40000", "3500", "50000"),
        faixa("acima de 50001, R$ 4000", "50001", "4000", None),
    ]
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": {}, "elementos": elementos, "parametros": {}}]
    )
    payload = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = texto
    rotulos = {"construto": "faixa_valor"}
    antes = (await cliente.get("/metrics")).text

    recebida = mensagem(payload)
    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    depois = (await cliente.get("/metrics")).text
    nome = "codegen_extracao_elementos_total"
    assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == 2


async def test_nao_descarta_elemento_generico(monkeypatch: pytest.MonkeyPatch) -> None:
    elemento = {
        "construto_pretendido": "forma_privada",
        "descricao": "PARAFRASE_PRIVADA",
        "trecho": TEXTO,
    }
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": {}, "elementos": [elemento], "parametros": {}}]
    )
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(extracao["representacao"])["especificacoes"] == [
        {"ref": "elem.1", "construto": "generico", "descricao": "PARAFRASE_PRIVADA"}
    ]


TEXTO_DOS_VENDEDORES = (
    "A regra vale em todas as lojas e em todas as marcas, somente para o cargo 100, com "
    "comissão de 3% sobre suas vendas individuais."
)
REPETICAO_DO_NUCLEO = {
    "nucleo": {
        "loja": {"valor": [], "trecho": "todas as lojas"},
        "marca": {"valor": [], "trecho": "todas as marcas"},
        "cargo": [{"valor": "100", "trecho": "cargo 100"}],
        "percentual": {"valor": Decimal("0.03"), "trecho": "3%"},
    },
    "elementos": [
        {
            "construto_pretendido": "generico",
            "descricao": "comissão de 3% sobre suas vendas individuais.",
            "trecho": "com comissão de 3% sobre suas vendas individuais.",
        }
    ],
    "parametros": {},
}
REDUNDANTES = "codegen_extracao_elementos_redundantes_total"


async def test_repeticao_do_nucleo_descartada_aparece_no_log_e_na_metrica(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    ambiente = AmbienteExtracao(monkeypatch, [REPETICAO_DO_NUCLEO])
    payload = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = TEXTO_DOS_VENDEDORES
    antes = (await cliente.get("/metrics")).text
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [artefato] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(artefato["representacao"])["especificacoes"] == []
    depois = (await cliente.get("/metrics")).text
    assert amostra(depois, REDUNDANTES, {}) - amostra(antes, REDUNDANTES, {}) == 1
    [concluida] = [log for log in logs if log["message"] == "extraction finished"]
    assert concluida["extra"]["elementos_redundantes"] == 1
    assert concluida["extra"]["elementos_por_construto"] == {"nucleo": 4}
    assert "vendas individuais" not in simplejson.dumps(logs)


async def test_extracao_reaproveitada_nao_conta_de_novo_a_repeticao_descartada(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    """A contagem não é gravada com o artefato: a tentativa que o reaproveita não a conhece."""
    ambiente = AmbienteExtracao(monkeypatch, [REPETICAO_DO_NUCLEO])
    payload = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = TEXTO_DOS_VENDEDORES
    antes = (await cliente.get("/metrics")).text
    original = ambiente.producers.no_concluido.side_effect
    ambiente.producers.no_concluido.side_effect = RuntimeError("BROKER_PRIVADO")
    await ambiente.consumer.receber(mensagem(payload))
    ambiente.producers.no_concluido.side_effect = original
    reentregue = mensagem(payload)

    await ambiente.consumer.receber(reentregue)

    reentregue.ack.assert_awaited_once_with()
    depois = (await cliente.get("/metrics")).text
    assert amostra(depois, REDUNDANTES, {}) - amostra(antes, REDUNDANTES, {}) == 1
    [concluida] = [log for log in logs if log["message"] == "extraction finished"]
    assert concluida["extra"]["extracao_reutilizada"] is True
    assert "elementos_redundantes" not in concluida["extra"]


def amostra(texto: str, nome: str, rotulos: dict[str, str]) -> float:
    return next(
        (
            s.value
            for f in text_string_to_metric_families(texto)
            for s in f.samples
            if s.name == nome and s.labels == rotulos
        ),
        0.0,
    )


@pytest.mark.parametrize("trecho_percentual", ["2,5%", "2,5 por cento"])
@pytest.mark.parametrize(
    "falha",
    [
        None,
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
    trecho_percentual: str,
) -> None:
    texto = TEXTO.replace("2,5%", trecho_percentual)
    elemento = {
        "construto_pretendido": "FORMA_PRIVADA",
        "descricao": "PARAFRASE_PRIVADA",
        "trecho": texto,
    }
    parametros = {"orcamento": {"valor": Decimal("500000"), "trecho": texto}}
    ambiente = AmbienteExtracao(
        monkeypatch,
        [
            {
                "nucleo": {
                    **NUCLEO_RASCUNHO,
                    "percentual": {"valor": Decimal("0.025"), "trecho": trecho_percentual},
                },
                "elementos": [elemento, {"trecho": texto}],
                "parametros": parametros,
            }
        ],
    )
    payload = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = texto
    aguardando = asyncio.Event()
    if falha == "transcricao_indisponivel":
        ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = ""
    elif falha == "saida_invalida":
        ambiente.modelo_extracao.messages = iter([AIMessage(content="RESPOSTA_PRIVADA_INVALIDA")])
    elif falha in ("provedor", "cancelamento"):

        async def falhar(*args: Any, **kwargs: Any) -> Any:
            if falha == "cancelamento":
                aguardando.set()
                await asyncio.Event().wait()
            raise RuntimeError("TRANSCRICAO_PRIVADA_DO_PROVEDOR")

        monkeypatch.setattr(FakeChatModel, "ainvoke", falhar)
    elif falha == "publicacao":
        ambiente.producers.regra_extraida.side_effect = RuntimeError("BROKER_PRIVADO")
    elif falha == "persistencia":
        ambiente.banco.falhar_em = ("extracoes_regras",)
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
    for nome, esperado in (
        ("job_runs_total", 1),
        ("job_failures_total", 1 if falha else 0),
        ("job_duration_seconds_count", 1),
    ):
        rotulos = {"job_name": "extract_rule"}
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == esperado
    assert amostra(depois, "job_duration_seconds_sum", rotulos) > amostra(
        antes, "job_duration_seconds_sum", rotulos
    )
    for nome, label, valor in (
        ("codegen_extracao_elementos_total", "construto", "nucleo"),
        ("codegen_extracao_elementos_total", "construto", "generico"),
        ("codegen_extracao_rebaixamentos_total", "motivo", "construto_nao_habilitado"),
        ("codegen_extracao_rebaixamentos_total", "motivo", "campo_obrigatorio_ausente"),
    ):
        rotulos = {label: valor}
        quantidade = 2 if label == "construto" else 1
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == (
            0 if falha else quantidade
        )
    for parametro, esperado_resultado in (
        ("orcamento", "extraido"),
        ("meta_venda", "ausente"),
        ("competencias", "ausente"),
    ):
        for resultado_label in ("extraido", "ausente"):
            rotulos = {"parametro": parametro, "resultado": resultado_label}
            delta = amostra(depois, "codegen_extracao_parametros_total", rotulos) - amostra(
                antes, "codegen_extracao_parametros_total", rotulos
            )
            assert delta == (0 if falha else int(resultado_label == esperado_resultado))
    if falha:
        rotulos = {"classe": falha}
        assert (
            amostra(depois, "codegen_extracao_falhas_total", rotulos)
            - amostra(antes, "codegen_extracao_falhas_total", rotulos)
            == 1
        )
    else:
        [extracao] = ambiente.banco.tabela("extracoes_regras")
        assert simplejson.loads(extracao["representacao"], use_decimal=True)["nucleo"] == NUCLEO
        anteriores = depois
        await ambiente.consumer.receber(mensagem(payload))
        posteriores = (await cliente.get("/metrics")).text
        assert amostra(posteriores, "job_runs_total", {"job_name": "extract_rule"}) == amostra(
            anteriores, "job_runs_total", {"job_name": "extract_rule"}
        )
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    validador = Draft202012Validator(schema, format_checker=FormatChecker())
    do_no = [log for log in logs if log.get("no") == "extracao_parametros"]
    assert [log["message"] for log in do_no] == [
        "extraction started",
        "extraction failed" if falha else "extraction finished",
    ]
    for log in logs:
        validador.validate(log)
        assert log["job_id"] == payload["job_id"]
    assert do_no[-1]["extra"]["extracao_reutilizada"] is False
    if not falha:
        assert do_no[-1]["extra"]["parametros_extraidos"] == ["orcamento"]
    for privado in (
        texto,
        "PARAFRASE_PRIVADA",
        "FORMA_PRIVADA",
        "RESPOSTA_PRIVADA",
        "TRANSCRICAO_PRIVADA",
        "BROKER_PRIVADO",
        "representacao",
    ):
        assert privado not in simplejson.dumps(logs)
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None


@pytest.mark.parametrize(
    ("tipo_erro", "motivo"),
    [
        (RuntimeError, "falha_na_operacao"),
        (ValueError, "falha_na_operacao"),
    ],
)
async def test_falha_inesperada_da_chamada_identifica_motivo_sem_expor_excecao(
    monkeypatch: pytest.MonkeyPatch,
    logs: list[dict[str, Any]],
    tipo_erro: type[Exception],
    motivo: str,
) -> None:
    """Timeout e erro de conexão não entram aqui: desde a T-268 eles vão para a espera do
    provedor (`test_indisponibilidade_do_provedor.py`), e só o que não é indisponibilidade
    chega ao tratamento de falha do nó."""
    ambiente = AmbienteExtracao(monkeypatch)
    payload = ambiente.entrada()
    monkeypatch.setattr(
        FakeChatModel, "ainvoke", AsyncMock(side_effect=tipo_erro("SEGREDO_DO_PROVEDOR"))
    )
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.nack.assert_awaited_once_with(requeue=True)
    [falha] = [log for log in logs if log["message"] == "extraction failed"]
    assert falha["job_id"] == payload["job_id"]
    assert falha["no"] == "extracao_parametros"
    assert falha["extra"] == {
        "classe": "provedor",
        "motivo": motivo,
        "operacao": "extrair_regra",
        "extracao_reutilizada": False,
    }
    assert "SEGREDO_DO_PROVEDOR" not in simplejson.dumps(logs)
    assert "exception" not in falha


@pytest.mark.parametrize(
    ("metodo", "operacao"),
    [
        ("etapa_alterada", "publicar_etapa_alterada"),
        ("regra_extraida", "publicar_regra_extraida"),
        ("no_concluido", "publicar_no_concluido"),
    ],
)
async def test_falha_de_publicacao_identifica_o_evento_sem_expor_excecao(
    monkeypatch: pytest.MonkeyPatch,
    logs: list[dict[str, Any]],
    metodo: str,
    operacao: str,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    getattr(ambiente.producers, metodo).side_effect = ConnectionError("SEGREDO_DO_BROKER")
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.nack.assert_awaited_once_with(requeue=True)
    [falha] = [log for log in logs if log["message"] == "extraction failed"]
    assert falha["extra"] == {
        "classe": "publicacao",
        "motivo": "conexao",
        "operacao": operacao,
        "extracao_reutilizada": False,
    }
    assert "SEGREDO_DO_BROKER" not in simplejson.dumps(logs)


@pytest.mark.parametrize(
    ("erro", "motivo"),
    [
        (TimeoutError("SEGREDO_DO_BROKER"), "timeout"),
        (ReadTimeout("SEGREDO_DO_BROKER"), "timeout"),
        (ConnectionError("SEGREDO_DO_BROKER"), "conexao"),
        (ConnectError("SEGREDO_DO_BROKER"), "conexao"),
        (RuntimeError("SEGREDO_DO_BROKER"), "falha_na_operacao"),
    ],
)
async def test_falha_de_infraestrutura_identifica_a_classe_do_erro(
    monkeypatch: pytest.MonkeyPatch,
    logs: list[dict[str, Any]],
    erro: Exception,
    motivo: str,
) -> None:
    """A publicação é o caminho que ainda vê timeout e erro de conexão crus: na chamada ao
    modelo eles passaram a ser indisponibilidade do provedor, com espera e janela."""
    ambiente = AmbienteExtracao(monkeypatch)
    ambiente.producers.etapa_alterada.side_effect = erro
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.nack.assert_awaited_once_with(requeue=True)
    [falha] = [log for log in logs if log["message"] == "extraction failed"]
    assert falha["extra"]["classe"] == "publicacao"
    assert falha["extra"]["motivo"] == motivo
    assert "SEGREDO_DO_BROKER" not in simplejson.dumps(logs)


@pytest.mark.parametrize(("duracao", "falha"), [(45.0, False), (180.0, True)])
async def test_duracao_longa_ocupa_buckets_finitos_em_sucesso_e_falha(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    duracao: float,
    falha: bool,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    instantes = iter([0.0, duracao])
    monkeypatch.setattr("app.graph.nodes.extract_rule.perf_counter", lambda: next(instantes))
    if falha:
        monkeypatch.setattr(
            FakeChatModel, "ainvoke", AsyncMock(side_effect=RuntimeError("privado"))
        )
    antes = (await cliente.get("/metrics")).text
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    if falha:
        recebida.nack.assert_awaited_once_with(requeue=True)
    else:
        recebida.ack.assert_awaited_once_with()
    depois = (await cliente.get("/metrics")).text
    for limite in (10.0, 30.0, 60.0, 120.0, 240.0, 300.0):
        rotulos = {"job_name": "extract_rule", "le": str(limite)}
        assert amostra(depois, "job_duration_seconds_bucket", rotulos) - amostra(
            antes, "job_duration_seconds_bucket", rotulos
        ) == (1 if duracao <= limite else 0)
    for nome, delta in (("job_duration_seconds_sum", duracao), ("job_duration_seconds_count", 1)):
        rotulos = {"job_name": "extract_rule"}
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == pytest.approx(
            delta
        )


@pytest.mark.parametrize(
    ("rascunho", "esperado"),
    [
        ({}, {}),
        (
            {"percentual": {"valor": Decimal("0.025"), "trecho": "2,5%"}},
            {"percentual": Decimal("0.025")},
        ),
        ({"loja": [{"valor": "13", "trecho": "loja 13"}]}, {"loja": ["13"]}),
        ({"percentual": {"valor": Decimal("0.04"), "trecho": "2,5%"}}, {}),
    ],
)
async def test_nucleo_do_modelo_so_chega_ao_artefato_com_lastro(
    monkeypatch: pytest.MonkeyPatch, rascunho: dict[str, Any], esperado: dict[str, Any]
) -> None:
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": rascunho, "elementos": [], "parametros": {}}]
    )
    recebida = mensagem(ambiente.entrada())

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [artefato] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(artefato["representacao"], use_decimal=True) == {
        "nucleo": esperado,
        "especificacoes": [],
    }


async def test_loja_dita_por_extenso_chega_ao_artefato_sem_rebaixamento_nem_texto_no_log(
    monkeypatch: pytest.MonkeyPatch, cliente: AsyncClient, logs: list[dict[str, Any]]
) -> None:
    texto = "loja sessenta e oito produto preto com dois por cento REGRA_PRIVADA_VOZ"
    rascunho = {
        "percentual": {"valor": Decimal("0.02"), "trecho": "dois por cento"},
        "loja": [{"valor": "68", "trecho": "loja sessenta e oito"}],
        "marca": [{"valor": "PRETO", "trecho": "produto preto"}],
    }
    ambiente = AmbienteExtracao(
        monkeypatch, [{"nucleo": rascunho, "elementos": [], "parametros": {}}]
    )
    payload = ambiente.entrada(origem="voz")
    ambiente.banco.transcricoes[UUID(payload["submissao_id"])] = texto
    antes = (await cliente.get("/metrics")).text
    recebida = mensagem(payload)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [artefato] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(artefato["representacao"], use_decimal=True) == {
        "nucleo": {"percentual": Decimal("0.02"), "loja": ["68"], "marca": ["10"]},
        "especificacoes": [],
    }
    assert simplejson.loads(artefato["rebaixamentos"]) == []
    depois = (await cliente.get("/metrics")).text
    for motivo in ("valor_sem_lastro", "codigo_fora_do_vocabulario", "termo_ambiguo"):
        rotulos = {"motivo": motivo}
        nome = "codegen_extracao_rebaixamentos_total"
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == 0
    do_no = [log for log in logs if log.get("no") == "extracao_parametros"]
    assert [log["message"] for log in do_no] == ["extraction started", "extraction finished"]
    assert do_no[-1]["extra"]["rebaixamentos_por_motivo"] == {}
    for privado in ("sessenta", "REGRA_PRIVADA_VOZ", texto):
        assert privado not in simplejson.dumps(logs)


async def test_correlacao_e_restaurada_entre_dois_jobs(
    monkeypatch: pytest.MonkeyPatch, logs: list[dict[str, Any]]
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    primeiro, segundo = ambiente.entrada(), ambiente.entrada()
    ambiente.banco.transcricoes[UUID(primeiro["submissao_id"])] = ""
    token_job = job_id_ctx.set("contexto_anterior")
    token_no = no_ctx.set("decisao")
    try:
        await ambiente.consumer.receber(mensagem(primeiro))
        assert job_id_ctx.get() == "contexto_anterior"
        assert no_ctx.get() == "decisao"
        await ambiente.consumer.receber(mensagem(segundo))
        assert job_id_ctx.get() == "contexto_anterior"
        assert no_ctx.get() == "decisao"
    finally:
        no_ctx.reset(token_no)
        job_id_ctx.reset(token_job)
    assert [
        (log["job_id"], log["message"]) for log in logs if log.get("no") == "extracao_parametros"
    ] == [
        (primeiro["job_id"], "extraction started"),
        (primeiro["job_id"], "extraction failed"),
        (segundo["job_id"], "extraction started"),
        (segundo["job_id"], "extraction finished"),
    ]


@pytest.mark.parametrize("origem", ["formulario", "reprocessamento", "texto"])
async def test_guarda_do_no_recusa_entrada_invalida_pelo_grafo(
    monkeypatch: pytest.MonkeyPatch,
    origem: str,
) -> None:
    from app.falhas import FalhaDoJobError
    from app.graph.entrypoint import run_to_completion

    ambiente = AmbienteExtracao(monkeypatch)
    state: Any = {"job_id": str(uuid4()), "origem": origem, "competencias": ["2025-11"]}
    if origem != "texto":
        state["submissao_id"] = str(uuid4())

    with pytest.raises(FalhaDoJobError) as falha:
        await run_to_completion(
            state["job_id"], state, sessoes=ambiente.banco, producers=ambiente.producers
        )

    assert falha.value.etapa == "extracao_parametros"
    assert ambiente.modelo_extracao.seen_messages == []
    assert ambiente.banco.sql_executado == []


async def test_regra_gravada_abre_outro_ciclo_sem_repetir_extracao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ambiente = AmbienteExtracao(monkeypatch)
    entrada = ambiente.entrada()
    await ambiente.consumer.receber(mensagem(entrada))
    versao = {
        **entrada,
        "regra_id": str(uuid4()),
        "orcamento": Decimal("500000"),
        "meta_venda": Decimal("12000000"),
    }
    recebida = mensagem(versao)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    assert len(ambiente.modelo_extracao.seen_messages) == 1
    assert len(ambiente.modelo.seen_messages) == 1
    assert (await ambiente.estado(entrada)).next == ()
    assert (await ambiente.estado(versao)).next == ("await_execution",)
    assert (await ambiente.estado(entrada)).values.get("regra_id") is None
    assert (await ambiente.estado(versao)).values["regra_id"] == versao["regra_id"]
    ambiente.producers.regra_extraida.assert_awaited_once()
    ambiente.producers.executar_codigo.assert_awaited_once()


@pytest.mark.parametrize("sem_lastro", [False, True])
async def test_condicao_limiar_contada_no_no_sem_expor_texto(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
    sem_lastro: bool,
) -> None:
    texto = "Se a loja vender no mínimo R$ 50 mil no mês, a comissão é de 3%"
    saida = {
        "nucleo": {"percentual": {"valor": Decimal("0.03"), "trecho": "3%"}},
        "parametros": {},
        "elementos": [
            {
                "construto_pretendido": "condicao_limiar",
                "descricao": texto,
                "trecho": texto,
                "metrica": "venda_total",
                "escopo_agregacao": "loja",
                "operador": ">=",
                "limiar": {"valor": 70000 if sem_lastro else 50000, "trecho": "R$ 50 mil"},
            }
        ],
    }
    ambiente = AmbienteExtracao(monkeypatch, [saida])
    entrada = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(entrada["submissao_id"])] = texto
    recebida = mensagem(entrada)
    antes = (await cliente.get("/metrics")).text

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    depois = (await cliente.get("/metrics")).text
    for nome, delta in [
        ("condicao_limiar", 0 if sem_lastro else 1),
        ("generico", 1 if sem_lastro else 0),
    ]:
        labels = {"construto": nome}
        assert (
            amostra(depois, "codegen_extracao_elementos_total", labels)
            - amostra(antes, "codegen_extracao_elementos_total", labels)
            == delta
        )
    motivo = {"motivo": "valor_sem_lastro"}
    assert amostra(depois, "codegen_extracao_rebaixamentos_total", motivo) - amostra(
        antes, "codegen_extracao_rebaixamentos_total", motivo
    ) == (1 if sem_lastro else 0)
    validador = Draft202012Validator(
        simplejson.loads((CONTRATOS / "observability/log.schema.json").read_text()),
        format_checker=FormatChecker(),
    )
    for log in logs:
        validador.validate(log)
        assert log["job_id"] == entrada["job_id"]
    assert [log["message"] for log in logs if log.get("no") == "extracao_parametros"] == [
        "extraction started",
        "extraction finished",
    ]
    assert texto not in simplejson.dumps(logs)
    assert "R$ 50 mil" not in simplejson.dumps(logs)
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None


@pytest.mark.parametrize(
    ("texto", "trecho", "dimensao", "valores", "motivo", "campos"),
    [
        pytest.param(
            "Para todas as lojas, exceto a 13 e a 58",
            "exceto a 13 e a 58",
            "loja",
            [{"valor": "13", "trecho": "13"}, {"valor": "58", "trecho": "58"}],
            None,
            {"dimensao": "loja", "valores": ["13", "58"]},
            id="exclusao_valida",
        ),
        pytest.param(
            "Para todas as lojas, exceto a 13 e a 99",
            "exceto a 13 e a 99",
            "loja",
            [{"valor": "13", "trecho": "13"}, {"valor": "99", "trecho": "99"}],
            "codigo_fora_do_vocabulario",
            {"dimensao": "loja", "valores": ["13"]},
            id="codigo_desconhecido",
        ),
        pytest.param(
            "Para todas as lojas, exceto a 13 e a 99",
            "exceto a 13 e a 99",
            "loja",
            [{"valor": "13", "trecho": "13"}, {"valor": "99", "trecho": "13 e a 99"}],
            "codigo_fora_do_vocabulario",
            {"dimensao": "loja", "valores": ["13"]},
            id="codigo_desconhecido_com_trecho_amplo",
        ),
        pytest.param(
            "Comissão na loja 58. Para todas as lojas, exceto a 13",
            "exceto a 13",
            "loja",
            [{"valor": "13", "trecho": "13"}, {"valor": "58", "trecho": "loja 58"}],
            "valor_sem_lastro",
            {"dimensao": "loja", "valores": ["13"]},
            id="codigo_de_outra_frase",
        ),
        pytest.param(
            "Comissão de 2%. Este bônus não se aplica aos cargos de gerente",
            "Este bônus não se aplica aos cargos de gerente",
            "cargo",
            [{"valor": "gerente", "trecho": "gerente"}],
            "termo_ambiguo",
            None,
            id="excecao_de_bonus_sem_valor",
        ),
        pytest.param(
            "Comissão de 2%. Bônus de R$ 500 para todos, exceto os gerentes (150)",
            "exceto os gerentes (150)",
            "cargo",
            [{"valor": "150", "trecho": "gerentes (150)"}],
            "termo_ambiguo",
            None,
            id="excecao_recortada_de_bonus",
        ),
        pytest.param(
            "Bônus de R$ 500 para a matrícula 422. "
            "A regra inteira, inclusive o bônus, não se aplica aos gerentes (150)",
            "A regra inteira, inclusive o bônus, não se aplica aos gerentes (150)",
            "cargo",
            [{"valor": "150", "trecho": "gerentes (150)"}],
            None,
            {"dimensao": "cargo", "valores": ["150"]},
            id="global_inclusive_bonus",
        ),
        pytest.param(
            "Comissão de 2%; bônus de R$ 500 para a matrícula 422; "
            "a regra inteira não se aplica aos gerentes (150)",
            "a regra inteira não se aplica aos gerentes (150)",
            "cargo",
            [{"valor": "150", "trecho": "gerentes (150)"}],
            None,
            {"dimensao": "cargo", "valores": ["150"]},
            id="global_apos_ponto_e_virgula",
        ),
        pytest.param(
            "Comissão de 2%. Bônus de R$ 500 para a matrícula 422. "
            "Ele não se aplica aos gerentes (150)",
            "Ele não se aplica aos gerentes (150)",
            "cargo",
            [{"valor": "150", "trecho": "gerentes (150)"}],
            "termo_ambiguo",
            None,
            id="retoma_bonus_anterior",
        ),
    ],
)
async def test_exclusao_contada_no_no_sem_expor_texto(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
    texto: str,
    trecho: str,
    dimensao: str,
    valores: list[dict[str, str]],
    motivo: str | None,
    campos: dict[str, Any] | None,
) -> None:
    saida = {
        "nucleo": {},
        "parametros": {},
        "elementos": [
            {
                "construto_pretendido": "exclusao",
                "descricao": trecho,
                "trecho": trecho,
                "dimensao": dimensao,
                "valores": valores,
            }
        ],
    }
    ambiente = AmbienteExtracao(monkeypatch, [saida])
    entrada = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(entrada["submissao_id"])] = texto
    recebida = mensagem(entrada)
    antes = (await cliente.get("/metrics")).text

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [extracao] = ambiente.banco.tabela("extracoes_regras")
    esperado: dict[str, Any]
    if motivo is None:
        assert campos is not None
        esperado = {"ref": "elem.1", "construto": "exclusao", **campos}
    else:
        esperado = {"ref": "elem.1", "construto": "generico", "descricao": trecho}
        if campos is not None:
            esperado["campos"] = campos
    assert simplejson.loads(extracao["representacao"])["especificacoes"] == [esperado]
    assert simplejson.loads(extracao["rebaixamentos"]) == (
        [{"ref": "elem.1", "construto_pretendido": "exclusao", "motivo": motivo}] if motivo else []
    )
    depois = (await cliente.get("/metrics")).text
    for nome, delta in [
        ("exclusao", 0 if motivo else 1),
        ("generico", 1 if motivo else 0),
    ]:
        labels = {"construto": nome}
        assert (
            amostra(depois, "codegen_extracao_elementos_total", labels)
            - amostra(antes, "codegen_extracao_elementos_total", labels)
            == delta
        )
    for candidato in ("codigo_fora_do_vocabulario", "valor_sem_lastro", "termo_ambiguo"):
        labels = {"motivo": candidato}
        assert amostra(depois, "codegen_extracao_rebaixamentos_total", labels) - amostra(
            antes, "codegen_extracao_rebaixamentos_total", labels
        ) == (1 if candidato == motivo else 0)
    for nome, delta in (
        ("job_runs_total", 1),
        ("job_failures_total", 0),
        ("job_duration_seconds_count", 1),
    ):
        labels = {"job_name": "extract_rule"}
        assert amostra(depois, nome, labels) - amostra(antes, nome, labels) == delta
    validador = Draft202012Validator(
        simplejson.loads((CONTRATOS / "observability/log.schema.json").read_text()),
        format_checker=FormatChecker(),
    )
    for log in logs:
        validador.validate(log)
        assert log["job_id"] == entrada["job_id"]
    assert [log["message"] for log in logs if log.get("no") == "extracao_parametros"] == [
        "extraction started",
        "extraction finished",
    ]
    [conclusao] = [log for log in logs if log["message"] == "extraction finished"]
    assert conclusao["extra"]["rebaixamentos_por_motivo"] == ({motivo: 1} if motivo else {})
    assert texto not in simplejson.dumps(logs)
    assert trecho not in simplejson.dumps(logs)
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None


async def test_meses_enumerados_e_bonus_condicionado_preservam_regra_e_telemetria(
    monkeypatch: pytest.MonkeyPatch,
    cliente: AsyncClient,
    logs: list[dict[str, Any]],
) -> None:
    periodo = "agosto, outubro e dezembro de 2025"
    bonus = "Bônus de R$ 400,00 para o cargo 100 quando vender pelo menos R$ 45.000,00 no mês"
    taxa = "Gerente, cargo 150: 6% sobre as vendas da loja"
    texto = f"Simule {periodo}. {taxa}. {bonus}. CENARIO_RESERVADO".replace(
        "sobre as", "sobre\n  as"
    ).replace("quando vender", "quando\n  vender")
    rascunho = {
        "nucleo": {
            "taxas_por_cargo": [
                {"valor": {"cargo": "150", "percentual": Decimal("0.06")}, "trecho": taxa}
            ]
        },
        "parametros": {
            "competencias": {"valor": ["2025-08", "2025-10", "2025-12"], "trecho": periodo}
        },
        "elementos": [
            {
                "construto_pretendido": "bonus_fixo",
                "descricao": bonus,
                "trecho": bonus,
                "tipo_alvo": "filtro",
                "criterios": {"cargo": "100"},
                "valor": {"valor": Decimal("400"), "trecho": "R$ 400,00"},
            }
        ],
    }
    ambiente = AmbienteExtracao(monkeypatch, [rascunho])
    entrada = ambiente.entrada()
    ambiente.banco.transcricoes[UUID(entrada["submissao_id"])] = texto
    antes = (await cliente.get("/metrics")).text
    recebida = mensagem(entrada)

    await ambiente.consumer.receber(recebida)

    recebida.ack.assert_awaited_once_with()
    [salva] = ambiente.banco.tabela("extracoes_regras")
    assert simplejson.loads(salva["representacao"])["especificacoes"] == [
        {
            "ref": "elem.1",
            "construto": "generico",
            "descricao": bonus.replace("quando vender", "quando\n  vender"),
        }
    ]
    assert simplejson.loads(salva["representacao"], use_decimal=True)["nucleo"] == {
        "cargo": ["150"],
        "taxas_por_cargo": [{"cargo": "150", "percentual": Decimal("0.06")}],
    }
    assert simplejson.loads(salva["parametros"]) == {
        "competencias": ["2025-08", "2025-10", "2025-12"]
    }
    depois = (await cliente.get("/metrics")).text
    for nome, rotulos in (
        (
            "codegen_extracao_parametros_total",
            {"parametro": "competencias", "resultado": "extraido"},
        ),
        ("codegen_extracao_rebaixamentos_total", {"motivo": "termo_ambiguo"}),
        ("job_duration_seconds_count", {"job_name": "extract_rule"}),
    ):
        assert amostra(depois, nome, rotulos) - amostra(antes, nome, rotulos) == 1
    validador = Draft202012Validator(
        simplejson.loads((CONTRATOS / "observability/log.schema.json").read_text()),
        format_checker=FormatChecker(),
    )
    for log in logs:
        validador.validate(log)
        assert log["job_id"] == entrada["job_id"]
    assert [log["message"] for log in logs if log.get("no") == "extracao_parametros"] == [
        "extraction started",
        "extraction finished",
    ]
    assert "CENARIO_RESERVADO" not in simplejson.dumps(logs)
    assert bonus not in simplejson.dumps(logs)
    assert job_id_ctx.get() is None
    assert no_ctx.get() is None
