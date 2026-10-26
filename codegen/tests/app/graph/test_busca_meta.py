"""A busca no grafo compilado; só banco e transporte são substituídos nestes testes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import simplejson
from httpx import AsyncClient
from jsonschema import Draft202012Validator, FormatChecker
from langgraph.checkpoint.memory import InMemorySaver

from app.config import get_settings
from app.contratos.serializacao import serializar
from app.core.logger import job_id_ctx, no_ctx
from app.graph import entrypoint
from app.graph.core.engine import build_graph
from app.graph.core.state import AgentState
from app.graph.nodes.decision import decision
from app.mensageria.producers import Producers, Saida
from app.repositorio.regras import TentativasDeTaxa
from app.repositorio.resultados import ExecucaoDaMeta
from tests.app.graph import test_indisponibilidade_do_provedor as observabilidade
from tests.app.graph.test_indisponibilidade_do_provedor import amostra
from tests.app.test_mensageria import CONTRATOS, oficial

logs = observabilidade.logs


class Gravador(Producers):
    def __init__(self) -> None:
        self.publicacoes: list[tuple[str, dict[str, Any]]] = []
        self.falhar: str | None = None

    async def _publicar(self, dto: Saida, nome: str) -> None:
        payload = simplejson.loads(serializar(dto), use_decimal=True)
        oficial(nome).validate(payload)
        if nome == self.falhar:
            self.falhar = None
            raise RuntimeError("broker indisponível")
        self.publicacoes.append((nome, payload))

    def de(self, nome: str) -> list[dict[str, Any]]:
        return [p for n, p in self.publicacoes if n == nome]


class Ambiente:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.saver = InMemorySaver()
        self.producers = Gravador()
        self.sessoes = MagicMock()
        self.job, self.regra, self.codigo, self.original = (uuid4() for _ in range(4))
        self.thread = f"{self.job}:{self.regra}"
        self.config = {
            "configurable": {
                "thread_id": self.thread,
                "sessoes": self.sessoes,
                "producers": self.producers,
            }
        }
        self.encerrado = False
        self.resultados: dict[UUID, ExecucaoDaMeta] = {}
        self.estado: AgentState = {
            "job_id": str(self.job),
            "regra_id": str(self.regra),
            "codigo_gerado_id": str(self.codigo),
            "competencias": ["2025-11"],
            "orcamento": "100",
            "meta_venda": "1000",
            "resultado_id": str(self.original),
            "status_simulacao": "sucesso",
            "veredito": "viavel",
            "representacao_regra": {"nucleo": {"percentual": "0.05"}, "especificacoes": []},
        }
        self.resultados[self.original] = ExecucaoDaMeta(
            self.regra,
            self.codigo,
            "simulacao",
            Decimal("1000"),
            "sucesso",
            Decimal("50"),
            Decimal("100"),
            Decimal("1000"),
        )

        @asynccontextmanager
        async def checkpoint() -> AsyncIterator[InMemorySaver]:
            yield self.saver

        async def consultar(sessoes: Any, job: UUID, resultado: UUID) -> ExecucaoDaMeta:
            assert job == self.job
            return self.resultados[resultado]

        async def encerrado(sessoes: Any, job: UUID) -> bool:
            return self.encerrado

        monkeypatch.setattr(get_settings(), "BUSCA_META_ENABLED", True)
        monkeypatch.setattr(entrypoint, "get_checkpointer", checkpoint)
        for modulo in (
            "app.graph.entrypoint",
            "app.graph.nodes.decision",
            "app.graph.nodes.search_sales_target",
        ):
            monkeypatch.setattr(f"{modulo}.buscar_execucao_da_meta", consultar)
        monkeypatch.setattr("app.graph.nodes.search_sales_target.foi_encerrado", encerrado)
        monkeypatch.setattr(
            "app.graph.nodes.decision.contar_tentativas",
            AsyncMock(
                return_value=TentativasDeTaxa(0, False),
            ),
        )
        self.modelo = MagicMock(side_effect=AssertionError("A busca não chama a LLM"))
        monkeypatch.setattr("app.graph.nodes.code_generation.get_model", self.modelo)

    async def iniciar(self) -> None:
        graph = build_graph(self.saver)
        await graph.aupdate_state(self.config, self.estado, as_node="await_execution")
        await self.retomar(self.original)

    async def retomar(self, resultado: UUID) -> entrypoint.ResumeOutcome:
        gravado = self.resultados[resultado]
        token = job_id_ctx.set(str(self.job))
        try:
            return await entrypoint.resume_to_completion(
                self.thread,
                {
                    "resultado_id": str(resultado),
                    "status": gravado.status,
                    "proposito": gravado.proposito,
                    "veredito": "viavel"
                    if gravado.simulado is not None and gravado.simulado <= Decimal("100")
                    else "inviavel",
                },
                sessoes=self.sessoes,
                producers=self.producers,
            )
        finally:
            job_id_ctx.reset(token)

    def gravar(self, comissao: Decimal, status: str = "sucesso") -> UUID:
        comando = self.producers.de("executar-codigo")[-1]
        id = uuid4()
        self.resultados[id] = ExecucaoDaMeta(
            self.regra,
            self.codigo,
            "busca_meta",
            Decimal(str(float(comando["meta_venda"]))),
            status,
            comissao if status == "sucesso" else None,
            Decimal("100"),
            Decimal("1000"),
        )
        return id

    async def completar(self, modo: str = "sucesso") -> dict[str, Any]:
        for _ in range(12):
            comando = self.producers.de("executar-codigo")[-1]
            custo = {
                "sucesso": Decimal(str(comando["meta_venda"])) / 20,
                "nao_monotonica": Decimal("40"),
                "intervalo_esgotado": Decimal("50"),
                "falha_execucao": Decimal("0"),
            }[modo]
            resultado = self.gravar(custo, "erro_codigo" if modo == "falha_execucao" else "sucesso")
            await self.retomar(resultado)
            if self.producers.de("meta-venda-sugerida"):
                return self.producers.de("meta-venda-sugerida")[-1]
        raise AssertionError("Busca não terminou no limite")


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> Ambiente:
    return Ambiente(monkeypatch)


@pytest.mark.parametrize("sem_meta", [False, True])
async def test_meta_sugerida_referencia_execucao_real_maior_e_viavel(
    ambiente: Ambiente, sem_meta: bool
) -> None:
    if sem_meta:
        del ambiente.estado["meta_venda"]
        ambiente.resultados[ambiente.original].meta = None
    await ambiente.iniciar()
    evento = await ambiente.completar()
    gravado = ambiente.resultados[UUID(evento["resultado_id"])]
    assert evento["meta_venda"] == gravado.meta == Decimal("2000")
    assert gravado.simulado == Decimal("100")
    assert all(
        c["codigo_gerado_id"] == str(ambiente.codigo)
        and c["proposito"] == "busca_meta"
        and c["orcamento"] == 100
        for c in ambiente.producers.de("executar-codigo")
    )
    ambiente.modelo.assert_not_called()
    assert (await ambiente.retomar(ambiente.original)) == entrypoint.ResumeOutcome.ALREADY_FINISHED
    assert len(ambiente.producers.de("meta-venda-sugerida")) == 1


@pytest.mark.parametrize("motivo", ["nao_monotonica", "intervalo_esgotado", "falha_execucao"])
async def test_busca_publica_sem_solucao_com_motivo(ambiente: Ambiente, motivo: str) -> None:
    await ambiente.iniciar()
    evento = await ambiente.completar(motivo)
    assert evento["sem_solucao"] == {"motivo": motivo}
    assert "meta_venda" not in evento and "resultado_id" not in evento
    assert len(ambiente.producers.de("executar-codigo")) == (
        12 if motivo == "intervalo_esgotado" else 1
    )


async def test_resultados_antigos_nao_avancam_a_candidata_pendente(ambiente: Ambiente) -> None:
    await ambiente.iniciar()
    primeiro = ambiente.gravar(Decimal("100"))
    await ambiente.retomar(primeiro)
    segundo = ambiente.gravar(Decimal("200"))
    await ambiente.retomar(segundo)
    antes = list(ambiente.producers.publicacoes)
    for resultado in (ambiente.original, primeiro, segundo, primeiro):
        assert await ambiente.retomar(resultado) == entrypoint.ResumeOutcome.IGNORED
    assert ambiente.producers.publicacoes == antes
    await ambiente.completar()


async def test_falha_apos_planejar_candidata_retoma_a_mesma_publicacao(ambiente: Ambiente) -> None:
    await ambiente.iniciar()
    resultado = ambiente.gravar(Decimal("100"))
    ambiente.producers.falhar = "executar-codigo"
    with pytest.raises(RuntimeError, match="broker"):
        await ambiente.retomar(resultado)
    assert len(ambiente.producers.de("executar-codigo")) == 1
    await ambiente.retomar(resultado)
    assert [c["meta_venda"] for c in ambiente.producers.de("executar-codigo")] == [2000, 4000]
    assert await ambiente.retomar(resultado) == entrypoint.ResumeOutcome.IGNORED


async def test_encerramento_na_espera_impede_outro_candidato(ambiente: Ambiente) -> None:
    await ambiente.iniciar()
    ambiente.encerrado = True
    await ambiente.retomar(ambiente.gravar(Decimal("100")))
    assert len(ambiente.producers.de("executar-codigo")) == 1
    assert not ambiente.producers.de("meta-venda-sugerida")


@pytest.mark.parametrize(
    "caso", ["desabilitada", "igual", "sem_orcamento", "candidata", "inviavel"]
)
async def test_decisao_nao_abre_busca_fora_dos_criterios(
    ambiente: Ambiente, caso: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if caso == "desabilitada":
        monkeypatch.setattr(get_settings(), "BUSCA_META_ENABLED", False)
    elif caso == "igual":
        ambiente.resultados[ambiente.original].simulado = Decimal("100")
    elif caso == "sem_orcamento":
        del ambiente.estado["orcamento"]
        ambiente.estado.pop("veredito")
    elif caso == "candidata":
        ambiente.resultados[ambiente.original].proposito = "busca_meta"
    else:
        ambiente.estado["veredito"] = "inviavel"
    atualizacao = await decision(ambiente.estado, ambiente.config)
    assert atualizacao["encaminhamento"] != "busca_meta"


@pytest.mark.parametrize(
    "modo", ["sucesso", "nao_monotonica", "intervalo_esgotado", "falha_execucao"]
)
async def test_logs_e_metricas_do_fluxo(
    ambiente: Ambiente, cliente: AsyncClient, logs: list[dict[str, Any]], modo: str
) -> None:
    antes = (await cliente.get("/metrics")).text
    await ambiente.iniciar()
    await ambiente.completar(modo)
    depois = (await cliente.get("/metrics")).text
    rotulos = {
        "desfecho": "sugerida" if modo == "sucesso" else "sem_solucao",
        "motivo": "encontrada" if modo == "sucesso" else modo,
    }
    assert (
        amostra(depois, "codegen_busca_meta_total", rotulos)
        - amostra(antes, "codegen_busca_meta_total", rotulos)
        == 1
    )
    assert amostra(depois, "codegen_busca_meta_espera_seconds_count", {}) > amostra(
        antes, "codegen_busca_meta_espera_seconds_count", {}
    )
    assert amostra(depois, "codegen_busca_meta_processamento_seconds_count", {}) > amostra(
        antes, "codegen_busca_meta_processamento_seconds_count", {}
    )
    schema = simplejson.loads((CONTRATOS / "observability/log.schema.json").read_bytes())
    validador = Draft202012Validator(schema, format_checker=FormatChecker())
    busca = [linha for linha in logs if linha["message"].startswith("sales target")]
    assert {linha["message"] for linha in busca} >= {
        "sales target search started",
        "sales target search finished",
        "sales target candidate published",
    }
    for linha in busca:
        validador.validate(linha)
        assert linha["job_id"] == str(ambiente.job)
        assert linha["no"] == "search_sales_target"
        assert "comissao" not in linha.get("extra", {}) and "meta_venda" not in linha.get(
            "extra", {}
        )
    assert job_id_ctx.get() is None and no_ctx.get() is None


@pytest.mark.parametrize("campo", ["codigo_id", "regra_id", "proposito", "meta"])
async def test_resultado_de_outra_execucao_nao_retoma_a_busca(
    ambiente: Ambiente, campo: str
) -> None:
    await ambiente.iniciar()
    resultado = ambiente.gravar(Decimal("100"))
    outro = ambiente.resultados[resultado]
    setattr(
        outro,
        campo,
        {
            "codigo_id": uuid4(),
            "regra_id": uuid4(),
            "proposito": "simulacao",
            "meta": Decimal("3000"),
        }[campo],
    )
    antes = list(ambiente.producers.publicacoes)
    assert await ambiente.retomar(resultado) == entrypoint.ResumeOutcome.IGNORED
    assert ambiente.producers.publicacoes == antes


async def test_resultado_antecipado_espera_o_checkpoint_da_pausa(ambiente: Ambiente) -> None:
    await ambiente.iniciar()
    graph = build_graph(ambiente.saver)
    # Simula a janela entre a escolha persistida e o checkpoint posterior ao envio.
    snapshot = await graph.aget_state(ambiente.config)
    await graph.aupdate_state(ambiente.config, snapshot.values, as_node="search_sales_target")
    resultado = ambiente.gravar(Decimal("100"))
    assert await ambiente.retomar(resultado) == entrypoint.ResumeOutcome.NOT_PAUSED_YET
    await ambiente.retomar(ambiente.original)
    assert await ambiente.retomar(resultado) == entrypoint.ResumeOutcome.RESUMED


async def test_republicacao_do_desfecho_preserva_meta_resultado_e_identidade(
    ambiente: Ambiente,
) -> None:
    await ambiente.iniciar()
    ambiente.producers.falhar = "no-concluido"
    with pytest.raises(RuntimeError, match="broker"):
        await ambiente.completar("nao_monotonica")
    snapshot = await build_graph(ambiente.saver).aget_state(ambiente.config)
    await ambiente.retomar(UUID(snapshot.values["resultado_id"]))
    propostas = ambiente.producers.de("meta-venda-sugerida")
    assert len(propostas) == 2 and propostas[0] == propostas[1]
    assert len(ambiente.producers.de("executar-codigo")) == 1


async def test_regra_com_especificacoes_tambem_busca_meta(ambiente: Ambiente) -> None:
    """A busca simula o mesmo código, com todos os elementos da regra, nas metas candidatas."""
    ambiente.estado["representacao_regra"]["especificacoes"] = [
        {"ref": "elem.1", "construto": "generico", "descricao": "Bônus condicionado a vendas."}
    ]

    await ambiente.iniciar()
    evento = await ambiente.completar()

    assert evento["meta_venda"] == Decimal("2000")
    assert all(
        comando["proposito"] == "busca_meta"
        and comando["elementos_exigidos"] == ["nucleo.percentual", "elem.1"]
        for comando in ambiente.producers.de("executar-codigo")
    )


async def test_alternativa_de_taxa_viavel_tambem_busca_meta(
    ambiente: Ambiente, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.graph.nodes.decision.contar_tentativas",
        AsyncMock(
            return_value=TentativasDeTaxa(3, True),
        ),
    )
    await ambiente.iniciar()
    assert ambiente.producers.de("executar-codigo")[0]["proposito"] == "busca_meta"


async def test_candidata_inviavel_apenas_estreita_intervalo_sem_propor_taxa(
    ambiente: Ambiente,
) -> None:
    await ambiente.iniciar()
    await ambiente.retomar(ambiente.gravar(Decimal("120")))
    assert ambiente.producers.de("executar-codigo")[-1]["meta_venda"] == 1500
    assert not ambiente.producers.de("sugestao-adaptacao-proposta")
    assert not ambiente.producers.de("meta-venda-sugerida")


async def test_margem_pequena_sugere_meta_fracionaria_simulada(ambiente: Ambiente) -> None:
    ambiente.resultados[ambiente.original].simulado = Decimal("99.99999")
    await ambiente.iniciar()
    primeira = ambiente.producers.de("executar-codigo")[-1]["meta_venda"]
    assert Decimal("1000") < primeira < Decimal("1000.01")

    await ambiente.retomar(ambiente.gravar(Decimal("100.000001")))
    segunda = ambiente.producers.de("executar-codigo")[-1]["meta_venda"]
    assert Decimal("1000") < segunda < primeira
    resultado = ambiente.gravar(Decimal("99.999999"))
    await ambiente.retomar(resultado)

    sugestao = ambiente.producers.de("meta-venda-sugerida")
    assert len(sugestao) == 1
    assert sugestao[0]["meta_venda"] == segunda
    assert sugestao[0]["resultado_id"] == str(resultado)
    assert "sem_solucao" not in sugestao[0]
