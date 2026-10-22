"""Conjunto fechado de códigos dos conflitos da validação de domínio.

O ``motivo`` de um conflito é texto livre com valores da regra e não pode virar label nem
entrar em log; o código é o que métrica e log usam. Uma verificação nova acrescenta um
membro aqui, de forma aditiva.
"""

from enum import StrEnum


class CodigoConflito(StrEnum):
    PERCENTUAL_AUSENTE = "percentual_ausente"
    PERCENTUAL_NEGATIVO = "percentual_negativo"
    TAXA_CARGO_CONTRADITORIA = "taxa_cargo_contraditoria"
    TAXA_CARGO_FORA_ESCOPO = "taxa_cargo_fora_escopo"
    TAXA_CARGO_DESCONHECIDO = "taxa_cargo_desconhecido"
    ESCOPO_AUSENTE = "escopo_ausente"
    ORCAMENTO_AUSENTE = "orcamento_ausente"
    META_VENDA_AUSENTE = "meta_venda_ausente"
    VIGENCIA_INVERTIDA = "vigencia_invertida"
    EXCLUSAO_REPETIDA = "exclusao_repetida"
    FAIXA_INVERTIDA = "faixa_invertida"
    JANELA_INVERTIDA = "janela_invertida"
    LIMIAR_SEM_ESCOPO = "limiar_sem_escopo"
    # Parâmetros da simulação (T-280).
    ORCAMENTO_NEGATIVO = "orcamento_negativo"
    META_VENDA_NAO_POSITIVA = "meta_venda_nao_positiva"
    COMPETENCIA_NAO_PUBLICADA = "competencia_nao_publicada"
    PARAMETRO_SEM_LASTRO = "parametro_sem_lastro"
