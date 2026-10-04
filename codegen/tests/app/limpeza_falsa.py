"""`LimpezaDeCheckpoints` trocada por um falso nos testes que só provam o roteamento.

A limpeza real, com o lock e os checkpoints no Postgres, tem os seus próprios testes
(`tests/app/test_limpeza_postgres.py`).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.contratos.mensagens import JobEncerrado
from app.repositorio.encerramentos import EstadoDoEncerramento


class LimpezaFalsa:
    def __init__(self, encerramento: EstadoDoEncerramento | None = None) -> None:
        self.encerramento = encerramento
        self.registrados: list[JobEncerrado] = []
        self.limpezas: list[tuple[UUID, frozenset[str]]] = []
        self.erro_ao_registrar: Exception | None = None
        self.em_processamento = False

    async def registrar(self, evento: JobEncerrado) -> None:
        if self.erro_ao_registrar is not None:
            raise self.erro_ao_registrar
        self.registrados.append(evento)

    @asynccontextmanager
    async def durante_o_processamento(
        self, job_id: UUID
    ) -> AsyncIterator[EstadoDoEncerramento | None]:
        self.em_processamento = True
        try:
            yield self.encerramento
        finally:
            self.em_processamento = False

    async def limpar(self, job_id: UUID, liberados: frozenset[str] = frozenset()) -> None:
        # A limpeza real só consegue o lock exclusivo depois que o processamento solta o seu.
        assert not self.em_processamento, "a limpeza não pode rodar sob o lock do processamento"
        self.limpezas.append((job_id, liberados))
