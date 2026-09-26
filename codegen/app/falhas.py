"""Falhas que encerram o job, com a etapa do grafo que as reporta.

Uma falha permanente é a que uma reentrega da mensagem não corrige: a regra não existe, a
resposta do modelo não serve, o código não é extraível. A fronteira de mensageria trata todas
da mesma forma - avisa a `api` por `etapa-alterada` e rejeita a mensagem sem requeue -, então
o que cada uma precisa carregar é só a etapa em que aconteceu.

Falha transitória (banco ou broker indisponível, erro de rede do provedor) não entra aqui:
ela sobe como exceção comum e a reentrega do broker é a resposta certa.
"""

from typing import ClassVar

from app.contratos.mensagens import NoGrafo


class FalhaDoJobError(Exception):
    """Falha permanente: o job termina em `erro` e a mensagem é rejeitada sem requeue.

    Nunca carrega conteúdo de artefato - só qual verificação falhou. A mensagem da exceção
    não vai para log nem para evento, porque pode conter prompt, resposta ou código.
    """

    #: Etapa reportada em `etapa-alterada`, do vocabulário fechado de
    #: `contracts/domain/comum.schema.json#/$defs/no_grafo`. A `api` a usa para montar o
    #: motivo da transição (`erro_<etapa>`).
    etapa: ClassVar[NoGrafo]
