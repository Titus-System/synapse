"""Read-only access to `resultados_simulacao`, for the nodes that decide about a result.

Only `SELECT`: the row is written by the `worker`, that runs the code and apura os números
(migration `010-cria-resultados-simulacao.sql`). Nada aqui recalcula um total - o evento
traz referência, e o número vem da linha que o worker gravou (ADR-001).
"""

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

import simplejson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.correcao_codigo import FalhaDaExecucao
from app.falhas import FalhaDoJobError
from app.sugestao_adaptacao import LIMITE_DE_TENTATIVAS, TaxaSimulada, taxa_de_referencia


class ResultadoDesconhecidoError(Exception):
    """O resultado não existe para este job, ou não aponta para uma versão de regra.

    Não é falha do job: um resultado que este serviço não reconhece não diz nada sobre o
    job que o grafo conhece. Quem chama decide se rejeita a mensagem ou a reentrega.
    """


class ResultadoIndisponivelError(FalhaDoJobError):
    """O resultado referenciado não existe para este job, ou não tem totais utilizáveis.

    Nunca carrega conteúdo do resultado - só a etapa. Uma reentrega não faz a linha
    aparecer nem completar os totais, então a falha é permanente.
    """

    etapa = "sugestao_adaptacao"


class TotaisDaSimulacao:
    """O simulado e o orçamento persistidos, com o detalhamento que situa a parte fixa da comissão.

    `linhas` é None num resultado gravado antes do detalhamento.
    """

    __slots__ = ("linhas", "orcamento", "simulado")

    def __init__(
        self, simulado: Decimal, orcamento: Decimal, *, linhas: Mapping[str, object] | None
    ) -> None:
        self.simulado = simulado
        self.orcamento = orcamento
        self.linhas = linhas


def _decimal(valor: object) -> Decimal | None:
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, int) and not isinstance(valor, bool):
        return Decimal(valor)
    return None


def _objeto(valor: object) -> object:
    return simplejson.loads(valor, use_decimal=True) if isinstance(valor, str) else valor


async def buscar_totais(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, resultado_id: UUID
) -> TotaisDaSimulacao:
    """Load simulated cost, budget and the per-line detail from the worker's result row.

    Raises `ResultadoIndisponivelError` when the row is missing for that job or when any
    total is absent - o que acontece em todo desfecho que não é `sucesso`.
    """
    # `::text` pelo mesmo motivo de `buscar_regra`: sem o cast o driver decodifica o jsonb
    # com float, e o total viraria um número aproximado.
    consulta = text(
        "SELECT totais::text AS totais, linhas::text AS linhas FROM resultados_simulacao"
        " WHERE id = :resultado_id AND job_id = :job_id"
    )
    parametros = {"resultado_id": str(resultado_id), "job_id": str(job_id)}
    async with sessoes() as sessao:
        resultado = await sessao.execute(consulta, parametros)
        linha = resultado.mappings().one_or_none()

    if linha is None:
        raise ResultadoIndisponivelError("Simulation result not found for this job")

    totais = _objeto(linha["totais"])
    if not isinstance(totais, dict):
        raise ResultadoIndisponivelError("Simulation result has no totals")

    simulado = _decimal(totais.get("simulado"))
    orcamento = _decimal(totais.get("orcamento"))
    if simulado is None or orcamento is None:
        raise ResultadoIndisponivelError("Simulation result is missing simulado/orcamento")
    linhas = _objeto(linha.get("linhas"))
    return TotaisDaSimulacao(
        simulado, orcamento, linhas=linhas if isinstance(linhas, dict) else None
    )


async def buscar_taxas_simuladas(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, regra_id: UUID
) -> list[TaxaSimulada]:
    """Load the reference rate and simulated commission of `regra_id` and of the versions it adapts.

    A cadeia sobe por `regra_origem_id` enquanto a versão é uma sugestão e para na regra que
    a primeira sugestão adaptou: cada proposta reduz todas as taxas da versão de origem na mesma
    proporção, então os pares diferem só nessa proporção, que a taxa de referência representa.
    Uma versão de fora da cadeia pode ter outro escopo, e a execução candidata da busca da meta
    não é a simulação do job; nenhuma das duas vira par.
    Raises `ResultadoIndisponivelError` when a simulated version lacks a rate or simulado.
    """
    # `::text` pelo mesmo motivo de `buscar_totais`. A profundidade só limita a recursão.
    consulta = text(
        "WITH RECURSIVE cadeia AS ("
        "  SELECT id, regra_origem_id, origem, nucleo, especificacoes, 1 AS profundidade"
        "  FROM regras WHERE id = :regra_id AND job_id = :job_id"
        "  UNION ALL"
        "  SELECT r.id, r.regra_origem_id, r.origem, r.nucleo, r.especificacoes,"
        "  c.profundidade + 1"
        "  FROM regras r JOIN cadeia c ON r.id = c.regra_origem_id"
        "  WHERE c.origem = 'sugestao_adaptacao' AND r.job_id = :job_id"
        "  AND c.profundidade <= :limite"
        ")"
        " SELECT c.nucleo::text AS nucleo, c.especificacoes::text AS especificacoes,"
        " rs.totais::text AS totais FROM cadeia c"
        " JOIN codigos_gerados cg ON cg.regra_id = c.id AND cg.job_id = :job_id"
        " JOIN resultados_simulacao rs ON rs.codigo_gerado_id = cg.id AND rs.job_id = :job_id"
        " WHERE rs.status = 'sucesso' AND rs.proposito = 'simulacao'"
        " ORDER BY c.profundidade"
    )
    parametros = {"regra_id": str(regra_id), "job_id": str(job_id), "limite": LIMITE_DE_TENTATIVAS}
    async with sessoes() as sessao:
        resultado = await sessao.execute(consulta, parametros)
        linhas = resultado.mappings().all()

    taxas: list[TaxaSimulada] = []
    for linha in linhas:
        nucleo = _objeto(linha["nucleo"])
        especificacoes = _objeto(linha["especificacoes"])
        totais = _objeto(linha["totais"])
        referencia = (
            taxa_de_referencia({"nucleo": nucleo, "especificacoes": especificacoes})
            if isinstance(nucleo, dict) and isinstance(especificacoes, list)
            else None
        )
        simulado = _decimal(totais.get("simulado")) if isinstance(totais, dict) else None
        if referencia is None or simulado is None:
            raise ResultadoIndisponivelError("Simulated version is missing a rate or simulado")
        taxas.append(TaxaSimulada(referencia, simulado))
    return taxas


async def buscar_regra_do_resultado(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, resultado_id: UUID
) -> UUID:
    """Descobre qual versão de regra produziu `resultado_id`.

    `simulacao-concluida` não carrega a versão, e um job com mais de um ciclo tem mais de
    uma: o vínculo vem do código gerado que foi executado, que é de quem o resultado é.
    Raises `ResultadoDesconhecidoError` quando não há esse caminho para o job.
    """
    consulta = text(
        "SELECT c.regra_id FROM resultados_simulacao r"
        " JOIN codigos_gerados c ON c.id = r.codigo_gerado_id"
        " WHERE r.id = :resultado_id AND r.job_id = :job_id"
    )
    parametros = {"resultado_id": str(resultado_id), "job_id": str(job_id)}
    async with sessoes() as sessao:
        resultado = await sessao.execute(consulta, parametros)
        linha = resultado.mappings().one_or_none()

    if linha is None or linha["regra_id"] is None:
        raise ResultadoDesconhecidoError("No rule version behind this simulation result")
    return UUID(str(linha["regra_id"]))


async def posicao_do_codigo(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, codigo_gerado_id: UUID
) -> int:
    """A posição do código entre os gerados para a mesma versão da regra, a partir de 1.

    A `api` conta do mesmo jeito, pela ordem de criação, para decidir se a falha do código
    encerra o job; uma ordem diferente aqui faria os dois serviços divergirem. Zero quando o
    código não existe para o job.
    """
    consulta = text(
        "SELECT count(*) AS posicao FROM codigos_gerados alvo"
        " JOIN codigos_gerados c ON c.regra_id = alvo.regra_id AND c.job_id = alvo.job_id"
        " WHERE alvo.id = :codigo AND alvo.job_id = :job"
        " AND (c.criado_em, c.id) <= (alvo.criado_em, alvo.id)"
    )
    async with sessoes() as sessao:
        resultado = await sessao.execute(consulta, {"codigo": codigo_gerado_id, "job": job_id})
        posicao = resultado.scalar_one()
    return int(posicao)


async def buscar_falha_da_execucao(
    sessoes: async_sessionmaker[AsyncSession], job_id: UUID, resultado_id: UUID
) -> FalhaDaExecucao:
    """O status, o diagnóstico e as asserções violadas que o worker gravou para a execução.

    Raises `ResultadoDesconhecidoError` quando o resultado não existe para o job.
    """
    consulta = text(
        "SELECT status, diagnostico::text AS diagnostico, assercoes::text AS assercoes"
        " FROM resultados_simulacao WHERE id = :resultado AND job_id = :job"
    )
    async with sessoes() as sessao:
        resultado = await sessao.execute(consulta, {"resultado": resultado_id, "job": job_id})
        linha = resultado.mappings().one_or_none()
    if linha is None:
        raise ResultadoDesconhecidoError("Execution not found for this job")
    diagnostico = _objeto(linha["diagnostico"])
    assercoes = _objeto(linha["assercoes"])
    return FalhaDaExecucao(
        status=linha["status"],
        diagnostico=diagnostico if isinstance(diagnostico, dict) else None,
        assercoes_violadas=[
            assercao
            for assercao in (assercoes if isinstance(assercoes, list) else [])
            if isinstance(assercao, dict) and assercao.get("resultado") == "violada"
        ],
    )


class ExecucaoDaMeta:
    """Identidade e totais da execução, lidos juntos para conferir a candidata esperada."""

    def __init__(
        self,
        regra_id: UUID,
        codigo_id: UUID,
        proposito: str,
        meta: Decimal | None,
        status: str,
        simulado: Decimal | None,
        orcamento: Decimal | None,
        vendas_historicas: Decimal | None,
    ) -> None:
        self.regra_id = regra_id
        self.codigo_id = codigo_id
        self.proposito = proposito
        self.meta = meta
        self.status = status
        self.simulado = simulado
        self.orcamento = orcamento
        self.vendas_historicas = vendas_historicas


async def buscar_execucao_da_meta(
    sessoes: async_sessionmaker[AsyncSession],
    job_id: UUID,
    resultado_id: UUID,
) -> ExecucaoDaMeta:
    consulta = text(
        "SELECT c.regra_id, r.codigo_gerado_id, r.proposito, r.meta_venda, r.status,"
        " r.totais::text AS totais FROM resultados_simulacao r"
        " JOIN codigos_gerados c ON c.id = r.codigo_gerado_id AND c.job_id = r.job_id"
        " WHERE r.id = :resultado AND r.job_id = :job"
    )
    async with sessoes() as sessao:
        resultado = await sessao.execute(consulta, {"resultado": resultado_id, "job": job_id})
        linha = resultado.mappings().one_or_none()
    if linha is None or linha["regra_id"] is None:
        raise ResultadoDesconhecidoError("Execution not found for this job")
    totais = _objeto(linha["totais"])
    if not isinstance(totais, dict):
        totais = {}
    return ExecucaoDaMeta(
        UUID(str(linha["regra_id"])),
        UUID(str(linha["codigo_gerado_id"])),
        linha["proposito"],
        linha["meta_venda"],
        linha["status"],
        _decimal(totais.get("simulado")),
        _decimal(totais.get("orcamento")),
        _decimal(totais.get("vendas_historicas")),
    )
