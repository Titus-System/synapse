"""Falhas que encerram o job, com a etapa do grafo que as reporta.

Uma falha permanente é a que uma reentrega da mensagem não corrige: a regra não existe, a
resposta do modelo não serve, o código não é extraível. A fronteira de mensageria trata todas
da mesma forma - avisa a `api` por `etapa-alterada` e rejeita a mensagem sem requeue -, então
o que cada uma precisa carregar é só a etapa em que aconteceu.

Falha transitória (banco ou broker indisponível) não entra aqui: ela sobe como exceção comum e
a reentrega do broker é a resposta certa. O provedor de LLM indisponível é o caso à parte: a
espera acontece dentro do processamento da mensagem (`graph/core/llm/disponibilidade.py`), e só
o esgotamento da janela vira falha permanente, com a causa que a `api` traduz num motivo próprio.
"""

from typing import ClassVar, Literal

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

    #: Causa opcional de `etapa-alterada`, para a `api` dar ao job um motivo próprio. Sem ela,
    #: a falha segue o tratamento genérico.
    causa: ClassVar[Literal["provedor_indisponivel"] | None] = None


class ProvedorIndisponivelError(FalhaDoJobError):
    """O provedor de LLM seguiu indisponível durante toda a janela de novas tentativas.

    Cada nó que chama o modelo declara a sua subclasse, com a etapa em que a chamada falhou.
    """

    causa = "provedor_indisponivel"


class JobEncerradoDuranteEsperaError(Exception):
    """O usuário cancelou ou arquivou o job enquanto o codegen esperava o provedor.

    Não encerra o job nem reporta falha: o job já acabou. Mora aqui, e não junto da espera,
    porque quem a traduz é a fronteira de mensageria - que a trata como qualquer mensagem de
    job encerrado, com `ack` e sem avisar a `api` - e ela não enxerga o interior do grafo.
    """
