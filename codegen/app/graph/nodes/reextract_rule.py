"""Re-extract a correction and propose the corrected version to the api (T-221).

The re-extraction cycle ends here, publishing `correcao-proposta` or failing for good on
`extracao_parametros`, where the api reopens the correction in a new round. It never pauses.
"""

import asyncio
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from httpx import NetworkError, TimeoutException
from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contratos.mensagens import (
    ConclusaoDaTrilha,
    CorrecaoProposta,
    EtapaAlterada,
    NoConcluido,
    NoGrafo,
    ParametrosSimulacao,
)
from app.core.logger import get_logger, job_id_ctx, no_ctx
from app.core.metrics.global_metrics import (
    CONSTRUTOS_DA_EXTRACAO,
    elementos_extraidos,
    falhas_extracao,
    job_duration,
    job_failures,
    job_runs,
    rebaixamentos_extracao,
)
from app.extracao.modelos import FalhaExtracaoError
from app.extracao.reextracao import aplicar_resposta_reextracao, reextrair_regra
from app.extracao.vocabulario import carregar_vocabulario
from app.falhas import (
    FalhaDoJobError,
    JobEncerradoDuranteEsperaError,
    ProvedorIndisponivelError,
)
from app.graph.core.llm import registry
from app.graph.core.llm.disponibilidade import (
    chamar_com_espera_do_provedor,
    ganchos_da_espera,
)
from app.graph.core.state import AgentState
from app.graph.nodes.validate_domain import parametros_do_job, verificar_versao
from app.graph.prompts.reextraction import montar_prompt_reextracao
from app.repositorio.artefatos import (
    buscar_resposta_gravada,
    gravar_prompt_e_resposta,
    id_do_evento_de_trilha,
)
from app.repositorio.regras import RegraInvalidaError, buscar_regra
from app.repositorio.rodadas_correcao import buscar_historico_correcao
from app.repositorio.submissoes import TranscricaoIndisponivelError, buscar_transcricao
from app.representacao_regra import RepresentacaoRegra

ETAPA: NoGrafo = "extracao_parametros"
logger = get_logger("app.graph.nodes.reextract_rule")


class EntradaReextracaoInvalidaError(FalhaDoJobError):
    etapa = ETAPA


class RegraDaCorrecaoIndisponivelError(FalhaDoJobError):
    """The corrected version does not exist for the job, or fails `RepresentacaoRegra`.

    `buscar_regra` reports it on `validacao_dominio`, where the read happens in a rule cycle. The
    api only recognizes a re-extraction failure on `extracao_parametros`.
    """

    etapa = ETAPA


class ProvedorIndisponivelReextracaoError(ProvedorIndisponivelError):
    etapa = ETAPA


class FalhaTransitoriaReextracaoError(RuntimeError):
    """Sanitized infrastructure failure; the consumer retries the message."""


def _motivo_da_falha(erro: BaseException, classe: str) -> str:
    # Classify by type: exception text can contain the correction, the rule or credentials.
    if isinstance(erro, FalhaDoJobError | JobEncerradoDuranteEsperaError | asyncio.CancelledError):
        return classe
    if isinstance(erro, TimeoutError | TimeoutException):
        return "timeout"
    if isinstance(erro, ConnectionError | NetworkError):
        return "conexao"
    return "falha_na_operacao"


async def _ler_regra(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, regra_id: UUID
) -> RepresentacaoRegra:
    regra = None
    with suppress(RegraInvalidaError):
        regra = await buscar_regra(sessoes, job_id, regra_id)
    # Fora do `suppress`, para a falha pública não carregar a original em __context__.
    if regra is None:
        raise RegraDaCorrecaoIndisponivelError("Corrected rule unavailable")
    return regra


async def reextract_rule(state: AgentState, config: RunnableConfig) -> AgentState:
    job_id = UUID(state["job_id"])
    token_job = job_id_ctx.set(str(job_id))
    token_no = no_ctx.set(ETAPA)
    inicio = perf_counter()
    job_runs.labels(job_name="reextract_rule").inc()
    # Os ids localizam a correção nos logs; o texto dela nunca entra.
    referencias: dict[str, str] = {}
    if "regra_origem_id" in state:
        referencias["regra_id"] = state["regra_origem_id"]
    if "submissao_correcao_id" in state:
        referencias["submissao_id"] = state["submissao_correcao_id"]
    logger.info("reextraction started", extra=referencias)
    classe = "publicacao"
    operacao = "publicar_etapa_alterada"
    resposta_reutilizada = False
    try:
        producers = config["configurable"]["producers"]
        sessoes = config["configurable"]["sessoes"]
        await producers.etapa_alterada(EtapaAlterada(job_id=job_id, etapa=ETAPA, status="iniciada"))
        classe = "entrada_invalida"
        operacao = "validar_entrada"
        if not (
            state.get("regra_origem_id")
            and state.get("submissao_correcao_id")
            and state.get("competencias")
        ):
            raise EntradaReextracaoInvalidaError("Invalid re-extraction input")
        regra_id = UUID(state["regra_origem_id"])
        submissao_id = UUID(state["submissao_correcao_id"])
        # O conjunto completo atual, nunca um patch: é o que a proposta devolve corrigido.
        parametros = parametros_do_job(state)
        classe = "persistencia"
        operacao = "buscar_regra"
        regra = await _ler_regra(sessoes, job_id, regra_id)
        operacao = "buscar_transcricao"
        texto = await buscar_transcricao(sessoes, submissao_id)
        operacao = "buscar_historico_correcao"
        historico = await buscar_historico_correcao(sessoes, job_id, submissao_id)
        # Recalculados, e não lidos da rodada: a validação é determinística, e a rodada guarda o
        # mesmo resultado. São dados do sistema, que mostram ao modelo o que o usuário responde,
        # inclusive os conflitos dos parâmetros.
        operacao = "recalcular_conflitos"
        validacao = await verificar_versao(
            sessoes, job_id, regra_id, regra.para_contrato(), parametros
        )
        conflitos = [
            {"elementos": list(conflito.elementos), "motivo": conflito.motivo}
            for conflito in validacao.conflitos
        ]
        # As competências publicadas, e não as do job: a correção pode levar o período a um mês
        # que o job não tinha.
        publicadas = carregar_vocabulario()["competencias_publicadas"]
        # Com as mesmas entradas, o prompt é o mesmo. Se ele já tem resposta gravada desde esta
        # correção, uma execução anterior caiu depois de gravá-la e pode ter publicado a
        # proposta: chamar o modelo de novo traria outra, e a trilha apontaria um prompt que não
        # gerou a versão que a api aplicou.
        operacao = "buscar_resposta_gravada"
        gravada = await buscar_resposta_gravada(
            sessoes,
            job_id=job_id,
            no=ETAPA,
            prompt=montar_prompt_reextracao(
                regra, parametros, conflitos, texto, publicadas, historico=historico
            ),
            submissao_id=submissao_id,
        )
        if gravada is not None:
            resposta_reutilizada = True
            operacao = "reaplicar_resposta_gravada"
            representacao, completos, diagnosticos = aplicar_resposta_reextracao(
                regra, parametros, gravada.conteudo, texto, publicadas
            )
            prompt_id, resposta_id = gravada.prompt_id, gravada.resposta_id
        else:
            classe = "provedor"
            operacao = "carregar_modelo"
            modelo = registry.get_model("extraction")
            metadados_modelo = registry.get_model_metadata("extraction")
            operacao = "reextrair_regra"
            avisar, encerrado = ganchos_da_espera(config, state, ETAPA)
            resultado = await chamar_com_espera_do_provedor(
                lambda: reextrair_regra(
                    regra,
                    parametros,
                    conflitos,
                    texto,
                    publicadas,
                    modelo=modelo,
                    metadados_modelo=metadados_modelo,
                    historico=historico,
                ),
                no=ETAPA,
                esgotada=ProvedorIndisponivelReextracaoError,
                avisar=avisar,
                encerrado=encerrado,
            )
            classe = "persistencia"
            operacao = "gravar_prompt_e_resposta"
            chamada = resultado.chamada
            prompt_id, resposta_id = await gravar_prompt_e_resposta(
                sessoes,
                job_id=job_id,
                no=ETAPA,
                prompt=chamada.prompt,
                modelo=chamada.modelo,
                resposta=chamada.resposta,
                consumo_tokens=chamada.consumo_tokens,
            )
            representacao = resultado.representacao
            completos = resultado.parametros
            diagnosticos = resultado.rebaixamentos
        classe = "publicacao"
        operacao = "publicar_correcao_proposta"
        await producers.correcao_proposta(
            CorrecaoProposta(
                job_id=job_id,
                regra_origem_id=regra_id,
                submissao_id=submissao_id,
                representacao=representacao,
                # O conjunto completo, mesmo sem mudança. Os valores já passaram pelo schema, e
                # um número inteiro do modelo chega como `int`, que o modo estrito recusaria.
                parametros=ParametrosSimulacao.model_validate(completos, strict=False),
            )
        )
        corrigida: dict[str, Any] = representacao.para_contrato()
        referencias_da_regra = [f"nucleo.{campo}" for campo in corrigida["nucleo"]]
        referencias_da_regra.extend(e["ref"] for e in corrigida["especificacoes"])
        operacao = "publicar_no_concluido"
        await producers.no_concluido(
            NoConcluido(
                # Pela correção, e não pelo prompt: a trilha tem uma linha por correção.
                evento_id=id_do_evento_de_trilha(job_id, ETAPA, submissao_id),
                job_id=job_id,
                no=ETAPA,
                concluido_em=datetime.now(UTC),
                regra_id=regra_id,
                prompt_id=prompt_id,
                conclusao=ConclusaoDaTrilha(
                    resumo="Correção reextraída; versão corrigida proposta à api.",
                    fontes=["submissoes.transcricao", "regras"],
                    elementos_extraidos=referencias_da_regra,
                ),
            )
        )
        contagens = Counter(
            e["construto"] if e["construto"] in CONSTRUTOS_DA_EXTRACAO else "outro"
            for e in corrigida["especificacoes"]
        )
        contagens["nucleo"] = len(corrigida["nucleo"])
        rebaixamentos = Counter(diagnostico.motivo for diagnostico in diagnosticos)
        for construto, quantidade in contagens.items():
            elementos_extraidos.labels(construto=construto).inc(quantidade)
        for motivo, quantidade in rebaixamentos.items():
            rebaixamentos_extracao.labels(motivo=motivo).inc(quantidade)
        logger.info(
            "reextraction finished",
            extra={
                **referencias,
                "prompt_id": str(prompt_id),
                "resposta_reutilizada": resposta_reutilizada,
                "elementos_por_construto": dict(contagens),
                "rebaixamentos_por_motivo": dict(rebaixamentos),
            },
        )
        return {"prompt_id": str(prompt_id), "resposta_id": str(resposta_id)}
    except (asyncio.CancelledError, Exception) as erro:
        if isinstance(erro, RegraDaCorrecaoIndisponivelError):
            classe = "regra_indisponivel"
        elif isinstance(erro, TranscricaoIndisponivelError):
            classe = "transcricao_indisponivel"
        elif isinstance(erro, FalhaExtracaoError):
            classe = "saida_invalida"
        elif isinstance(erro, asyncio.CancelledError | JobEncerradoDuranteEsperaError):
            # Decisão do usuário, e não falha da operação em curso, como em `extract_rule`.
            classe = "cancelamento"
        job_failures.labels(job_name="reextract_rule").inc()
        falhas_extracao.labels(classe=classe).inc()
        logger.warning(
            "reextraction failed",
            extra={
                **referencias,
                "classe": classe,
                "motivo": _motivo_da_falha(erro, classe),
                "operacao": operacao,
                "resposta_reutilizada": resposta_reutilizada,
            },
        )
        if isinstance(
            erro, FalhaDoJobError | JobEncerradoDuranteEsperaError | asyncio.CancelledError
        ):
            raise
    finally:
        job_duration.labels(job_name="reextract_rule").observe(perf_counter() - inicio)
        no_ctx.reset(token_no)
        job_id_ctx.reset(token_job)
    raise FalhaTransitoriaReextracaoError("Re-extraction infrastructure unavailable")
