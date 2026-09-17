from typing import Protocol
from uuid import UUID

from app.contratos.mensagens import ParametrosConfirmados, RegraSubmetida, SimulacaoConcluida

type Entrada = RegraSubmetida | ParametrosConfirmados | SimulacaoConcluida


class JobDesconhecidoError(Exception):
    """O roteador não encontrou o grafo correspondente ao job recebido."""


class RoteadorGrafo(Protocol):
    async def entregar(self, job_id: UUID, mensagem: Entrada) -> None:
        """Retorna só após processamento persistido; reentregas devem ser idempotentes.

        Resolve/cria o grafo de regra-submetida e retoma os demais pelo job_id.
        Lança JobDesconhecidoError se não houver grafo correspondente à mensagem.
        """
        ...
