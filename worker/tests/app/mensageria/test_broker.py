from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.config import Settings
from app.mensageria import broker
from app.mensageria.broker import conectar


@pytest.fixture
def canal(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Substitui o broker real, que o teste não possui."""
    canal = AsyncMock()
    conexao = MagicMock()
    conexao.channel = AsyncMock(return_value=canal)
    monkeypatch.setattr(broker, "connect_robust", AsyncMock(return_value=conexao))
    return canal


async def test_declara_a_fila_de_execucao_como_duravel(
    canal: AsyncMock, settings: Settings
) -> None:
    await conectar()

    assert canal.declare_queue.await_args_list == [
        call(settings.RABBITMQ_FILA_EXECUCAO, durable=True),
        call(
            f"{settings.RABBITMQ_FILA_EXECUCAO}.dlq",
            durable=True,
            exclusive=False,
            auto_delete=False,
        ),
    ]


async def test_habilita_confirmacoes_e_falha_para_publicacao_sem_rota(canal: AsyncMock) -> None:
    await conectar()

    broker.connect_robust.return_value.channel.assert_awaited_once_with(
        publisher_confirms=True, on_return_raises=True
    )


async def test_limita_o_canal_a_uma_execucao_por_vez(canal: AsyncMock) -> None:
    await conectar()

    canal.set_qos.assert_awaited_once_with(prefetch_count=1)
