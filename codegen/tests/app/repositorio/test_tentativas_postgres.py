"""As consultas da iteração da taxa nova no Postgres real, com as migrations da api."""

import os
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import simplejson
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.repositorio.regras import TentativasDeTaxa, contar_tentativas
from app.repositorio.resultados import buscar_taxas_simuladas, buscar_totais
from app.sugestao_adaptacao import TaxaSimulada

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="Requer Docker; habilitar com RUN_POSTGRES_INTEGRATION=1",
    ),
]


class Historico:
    """Grava versões, códigos e resultados como a api e o worker gravariam."""

    def __init__(self, dono: Any, usuario: UUID) -> None:
        self._dono = dono
        self._usuario = usuario

    async def job(self) -> UUID:
        job = uuid4()
        await self._dono.execute(
            "INSERT INTO jobs(id, usuario_id, status, competencias, orcamento, criado_em)"
            " VALUES($1, $2, 'simulando', '{2025-11}', 1700, now())",
            job,
            self._usuario,
        )
        return job

    async def versao(
        self,
        job: UUID,
        versao: int,
        origem: str,
        percentual: str | None,
        *,
        regra_origem: UUID | None = None,
        loja: str = "13",
        taxas_por_cargo: dict[str, str] | None = None,
        especificacoes: list[Any] | None = None,
    ) -> UUID:
        regra = uuid4()
        nucleo: dict[str, Any] = {"loja": [loja]}
        if percentual is not None:
            nucleo["percentual"] = Decimal(percentual)
        if taxas_por_cargo is not None:
            nucleo["taxas_por_cargo"] = [
                {"cargo": cargo, "percentual": Decimal(taxa)}
                for cargo, taxa in taxas_por_cargo.items()
            ]
        await self._dono.execute(
            "INSERT INTO regras(id, job_id, versao, origem, regra_origem_id, nucleo,"
            " especificacoes, hash, criada_em)"
            " VALUES($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, now())",
            regra,
            job,
            versao,
            origem,
            regra_origem,
            simplejson.dumps(nucleo, use_decimal=True),
            simplejson.dumps(especificacoes or [], use_decimal=True),
            uuid4().hex * 2,
        )
        return regra

    async def resultado(
        self,
        job: UUID,
        regra: UUID,
        simulado: str | None,
        *,
        status: str = "sucesso",
        proposito: str = "simulacao",
        orcamento: str | None = None,
        linhas: dict[str, Any] | None = None,
        codigo: UUID | None = None,
        diagnostico: dict[str, Any] | None = None,
        assercoes: list[Any] | None = None,
    ) -> UUID:
        if codigo is None:
            codigo = await self.codigo(job, regra)
        valores: dict[str, Decimal] = {}
        if simulado is not None:
            valores["simulado"] = Decimal(simulado)
        if orcamento is not None:
            valores["orcamento"] = Decimal(orcamento)
        totais = simplejson.dumps(valores) if valores else None
        resultado: UUID = await self._dono.fetchval(
            "INSERT INTO resultados_simulacao(job_id, codigo_gerado_id, status, totais,"
            " assercoes, proposito, linhas, diagnostico, criado_em) VALUES($1, $2, $3,"
            " $4::jsonb, $5::jsonb, $6, $7::jsonb, $8::jsonb, now()) RETURNING id",
            job,
            codigo,
            status,
            totais,
            simplejson.dumps(assercoes or []),
            proposito,
            None if linhas is None else simplejson.dumps(linhas, use_decimal=True),
            None if diagnostico is None else simplejson.dumps(diagnostico),
        )
        return resultado

    async def codigo(self, job: UUID, regra: UUID) -> UUID:
        prompt, codigo = uuid4(), uuid4()
        await self._dono.execute(
            "INSERT INTO prompts(id, job_id, no, conteudo, modelo, criado_em)"
            " VALUES($1, $2, 'geracao_codigo', 'p', '{}'::jsonb, now())",
            prompt,
            job,
        )
        await self._dono.execute(
            "INSERT INTO codigos_gerados(id, job_id, regra_id, linguagem, fonte, prompt_id,"
            " criado_em) VALUES($1, $2, $3, 'python', 'f', $4, now())",
            codigo,
            job,
            regra,
            prompt,
        )
        return codigo


@pytest_asyncio.fixture(loop_scope="module")
async def banco(
    postgres_extracao: tuple[int, Any],
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], Historico]]:
    porta, dono = postgres_extracao
    usuario = uuid4()
    await dono.execute(
        "INSERT INTO usuarios(id, login, senha_hash, nome, papel, criado_em)"
        " VALUES($1, $2, 'x', 'Teste', 'profissional_rh', now())",
        usuario,
        str(usuario),
    )
    engine = create_async_engine(
        f"postgresql+asyncpg://teste_codegen:teste-local@127.0.0.1:{porta}/postgres",
        hide_parameters=True,
    )
    try:
        yield (
            async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
            Historico(dono, usuario),
        )
    finally:
        await engine.dispose()


async def _cadeia_de_tres_tentativas(historico: Historico) -> tuple[UUID, list[UUID]]:
    """Original e duas alternativas simuladas; a terceira já gravada pela api, sem resultado."""
    job = await historico.job()
    original = await historico.versao(job, 1, "extracao", "0.025")
    await historico.resultado(job, original, "2000")
    await historico.resultado(job, original, "999", proposito="busca_meta")
    primeira = await historico.versao(job, 2, "sugestao_adaptacao", "0.02", regra_origem=original)
    await historico.resultado(job, primeira, "1800")
    await historico.resultado(job, primeira, None, status="erro_codigo")
    segunda = await historico.versao(job, 3, "sugestao_adaptacao", "0.0175", regra_origem=primeira)
    await historico.resultado(job, segunda, "1750.000000000000000001")
    terceira = await historico.versao(job, 4, "sugestao_adaptacao", "0.017", regra_origem=segunda)
    return job, [original, primeira, segunda, terceira]


async def test_conta_as_tentativas_ate_a_versao_simulada(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    """A proposta seguinte já gravada pela api não conta numa reentrega do resultado."""
    sessoes, historico = banco
    job, (original, _, segunda, _) = await _cadeia_de_tres_tentativas(historico)

    assert await contar_tentativas(sessoes, job, segunda) == TentativasDeTaxa(2, True)
    assert await contar_tentativas(sessoes, job, original) == TentativasDeTaxa(0, False)


async def test_os_pares_sao_as_simulacoes_do_job_na_cadeia_da_regra(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    """Nem a execução candidata da busca da meta nem a falha viram par."""
    sessoes, historico = banco
    job, (_, _, segunda, _) = await _cadeia_de_tres_tentativas(historico)

    taxas = await buscar_taxas_simuladas(sessoes, job, segunda)

    assert taxas == [
        TaxaSimulada(Decimal("0.0175"), Decimal("1750.000000000000000001")),
        TaxaSimulada(Decimal("0.02"), Decimal("1800")),
        TaxaSimulada(Decimal("0.025"), Decimal("2000")),
    ]


async def test_a_conta_e_do_job_e_os_pares_param_na_regra_que_a_sugestao_adaptou(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    """Uma correção depois de uma sugestão abre outra cadeia, com outro escopo."""
    sessoes, historico = banco
    job = await historico.job()
    original = await historico.versao(job, 1, "extracao", "0.03")
    await historico.resultado(job, original, "3000")
    sugerida = await historico.versao(job, 2, "sugestao_adaptacao", "0.02", regra_origem=original)
    await historico.resultado(job, sugerida, "2000")
    corrigida = await historico.versao(
        job, 3, "correcao", "0.025", regra_origem=sugerida, loja="14"
    )
    await historico.resultado(job, corrigida, "2500")
    alternativa = await historico.versao(
        job, 4, "sugestao_adaptacao", "0.02", regra_origem=corrigida, loja="14"
    )
    await historico.resultado(job, alternativa, "2100")

    assert await contar_tentativas(sessoes, job, alternativa) == TentativasDeTaxa(2, True)
    assert await buscar_taxas_simuladas(sessoes, job, alternativa) == [
        TaxaSimulada(Decimal("0.02"), Decimal("2100")),
        TaxaSimulada(Decimal("0.025"), Decimal("2500")),
    ]


async def test_os_pares_nao_atravessam_para_outro_job(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    sessoes, historico = banco
    _, (_, _, segunda, _) = await _cadeia_de_tres_tentativas(historico)
    outro_job = await historico.job()

    assert await buscar_taxas_simuladas(sessoes, outro_job, segunda) == []


async def test_os_pares_de_uma_regra_com_taxas_por_cargo_usam_a_taxa_de_referencia(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    """A primeira taxa positiva situa cada versão: o cargo sem comissão e o bônus ficam de fora."""
    sessoes, historico = banco
    job = await historico.job()
    bonus = [
        {
            "ref": "elem.1",
            "construto": "bonus_fixo",
            "alvo": {"tipo": "filtro", "valor": {"cargo": "100"}},
            "valor": 350,
        }
    ]
    original = await historico.versao(
        job,
        1,
        "extracao",
        None,
        taxas_por_cargo={"200": "0", "100": "0.03", "150": "0.05"},
        especificacoes=bonus,
    )
    await historico.resultado(job, original, "3000")
    sugerida = await historico.versao(
        job,
        2,
        "sugestao_adaptacao",
        None,
        regra_origem=original,
        taxas_por_cargo={"200": "0", "100": "0.0243", "150": "0.0405"},
        especificacoes=bonus,
    )
    await historico.resultado(job, sugerida, "2600")

    assert await buscar_taxas_simuladas(sessoes, job, sugerida) == [
        TaxaSimulada(Decimal("0.0243"), Decimal("2600")),
        TaxaSimulada(Decimal("0.03"), Decimal("3000")),
    ]


async def test_os_totais_trazem_o_detalhamento_com_as_comissoes_exatas(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    """A parte fixa da estimativa soma as comissões das linhas: em float, viriam aproximadas."""
    sessoes, historico = banco
    job = await historico.job()
    regra = await historico.versao(job, 1, "extracao", "0.03")
    linhas = {
        "2025-11": {
            "MATRIC-1": {
                "cod_loja": "14",
                "cod_marca": "10",
                "cod_cargo": "100",
                "comissao_baseline": Decimal("1000.10"),
                "comissao_simulada": Decimal("1000.10"),
                "diferenca": Decimal("0"),
                "contribuicoes": {},
            }
        }
    }
    resultado = await historico.resultado(job, regra, "2200", orcamento="2000", linhas=linhas)

    totais = await buscar_totais(sessoes, job, resultado)

    assert (totais.simulado, totais.orcamento) == (Decimal("2200"), Decimal("2000"))
    assert totais.linhas == linhas


async def test_os_totais_de_um_resultado_sem_detalhamento_vem_sem_linhas(
    banco: tuple[async_sessionmaker[AsyncSession], Historico],
) -> None:
    sessoes, historico = banco
    job = await historico.job()
    regra = await historico.versao(job, 1, "extracao", "0.03")
    resultado = await historico.resultado(job, regra, "2200", orcamento="2000")

    totais = await buscar_totais(sessoes, job, resultado)

    assert totais.linhas is None
