"""O executor do sandbox trocado por um falso nos testes que só provam a fiação do consumidor."""

import threading
from collections.abc import Callable
from typing import Any

from app.execucao.container import SaidaBruta
from app.execucao.preparo import PayloadContainer
from app.sandbox.envelope import SAIDA_POR_STATUS
from tests.app.execucao.envelopes import envelope, resultado_para, saida


def saida_para(
    payload: PayloadContainer, status: str = "sucesso", *, stderr: bytes = b"", **mudancas: Any
) -> SaidaBruta:
    """O que o container devolveria para este payload: o envelope leva os ids e as
    competências dele, senão a classificação o trataria como de outra execução, e o resultado de
    sucesso parte do baseline congelado dessas competências, senão o julgamento o reprovaria."""
    if status == "sucesso":
        mudancas.setdefault("resultado", resultado_para(payload.competencias))
    dados = envelope(
        status,
        job_id=str(payload.job_id),
        codigo_gerado_id=str(payload.codigo_gerado_id),
        competencias=payload.competencias,
        **mudancas,
    )
    return saida(dados, SAIDA_POR_STATUS[status], stderr=stderr)  # type: ignore[index]


class SandboxFalso:
    """Ocupa o lugar de `executar_no_sandbox`: a fiação do consumidor é provada aqui, e o
    container, pelos testes `docker` contra a imagem real."""

    def __init__(self) -> None:
        self.payloads: list[PayloadContainer] = []
        self.threads: list[int] = []
        self.cancelamentos: list[threading.Event | None] = []
        # Sem resposta definida, a execução termina em sucesso para o payload recebido.
        self.resposta: Callable[[PayloadContainer], SaidaBruta] = saida_para
        self.erro: Exception | None = None

    def __call__(
        self, payload: PayloadContainer, *, cancelar: threading.Event | None = None
    ) -> SaidaBruta:
        self.payloads.append(payload)
        self.cancelamentos.append(cancelar)
        self.threads.append(threading.get_ident())
        if self.erro is not None:
            raise self.erro
        return self.resposta(payload)
