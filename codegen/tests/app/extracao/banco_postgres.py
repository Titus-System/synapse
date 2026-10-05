"""Banco descartável com o DDL das migrations da API; nunca usa o compose do usuário."""

import asyncio
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def postgres_extracao() -> AsyncIterator[tuple[int, Any]]:
    container = (
        await asyncio.to_thread(
            subprocess.check_output,
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "-e",
                "POSTGRES_PASSWORD=teste-local",
                "-p",
                "127.0.0.1::5432",
                "postgres:18-alpine",
            ],
            text=True,
        )
    ).strip()
    dono = None
    try:
        porta = int(
            (
                await asyncio.to_thread(
                    subprocess.check_output,
                    ["docker", "port", container, "5432/tcp"],
                    text=True,
                )
            )
            .strip()
            .rsplit(":", 1)[1]
        )
        async with asyncio.timeout(45):
            while dono is None:
                try:
                    dono = await asyncpg.connect(
                        host="127.0.0.1",
                        port=porta,
                        user="postgres",
                        password="teste-local",
                        database="postgres",
                    )
                except (OSError, asyncpg.PostgresError):
                    await asyncio.sleep(0.2)
        migrations = (
            Path(__file__).resolve().parents[4] / "api/src/main/resources/db/changelog/changesets"
        )
        for arquivo in sorted(migrations.glob("*.sql")):
            sql = arquivo.read_text()
            for papel in ("api", "codegen", "worker"):
                sql = sql.replace("${usuario_" + papel + "}", "teste_" + papel)
            await dono.execute(sql)
        await dono.execute("ALTER ROLE teste_codegen WITH PASSWORD 'teste-local'")
        await dono.execute("ALTER ROLE teste_api WITH PASSWORD 'teste-local'")
        yield porta, dono
    finally:
        if dono is not None:
            await dono.close()
        await asyncio.to_thread(
            subprocess.run, ["docker", "stop", container], check=True, capture_output=True
        )


@pytest_asyncio.fixture(loop_scope="module")
async def banco_extracao(
    postgres_extracao: tuple[int, Any],
) -> AsyncIterator[tuple[Any, Any, Any, Any]]:
    porta, dono = postgres_extracao
    usuario, job, submissao = uuid4(), uuid4(), uuid4()
    await dono.execute(
        "INSERT INTO usuarios(id, login, senha_hash, nome, papel, criado_em)"
        " VALUES($1, $2, 'x', 'Teste', 'profissional_rh', now())",
        usuario,
        str(usuario),
    )
    await dono.execute(
        "INSERT INTO submissoes(id, usuario_id, tipo, transcricao, criado_em)"
        " VALUES($1, $2, 'voz', 'texto de teste', now())",
        submissao,
        usuario,
    )
    await dono.execute(
        "INSERT INTO jobs(id, usuario_id, submissao_id, status, competencias, orcamento, criado_em)"
        " VALUES($1, $2, $3, 'gerando_regra', '{2025-11}', 1000, now())",
        job,
        usuario,
        submissao,
    )
    engine = create_async_engine(
        f"postgresql+asyncpg://teste_codegen:teste-local@127.0.0.1:{porta}/postgres",
        hide_parameters=True,
    )
    try:
        yield (
            async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
            dono,
            job,
            submissao,
        )
    finally:
        await engine.dispose()
