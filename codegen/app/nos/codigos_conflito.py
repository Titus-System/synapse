"""Conjunto fechado de códigos dos conflitos da validação de domínio.

O ``motivo`` de um conflito é texto livre com valores da regra e não pode virar label nem
entrar em log; o código é o que métrica e log usam. Uma verificação nova acrescenta um
membro aqui, de forma aditiva.
"""

from enum import StrEnum


class CodigoConflito(StrEnum):
    PERCENTUAL_AUSENTE = "percentual_ausente"
    PERCENTUAL_NEGATIVO = "percentual_negativo"
    VIGENCIA_INVERTIDA = "vigencia_invertida"
    EXCLUSAO_REPETIDA = "exclusao_repetida"
    FAIXA_INVERTIDA = "faixa_invertida"
    JANELA_INVERTIDA = "janela_invertida"
    LIMIAR_SEM_ESCOPO = "limiar_sem_escopo"
