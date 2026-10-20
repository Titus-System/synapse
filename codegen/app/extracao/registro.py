from app.extracao.construto import Construto
from app.extracao.construtos import condicao_limiar
from app.extracao.construtos.bonus_fixo import BONUS_FIXO
from app.extracao.construtos.exclusao import EXCLUSAO
from app.graph.prompts.extraction import INSTRUCOES_CONDICAO_LIMIAR

# A ordem do registro é a das instruções no prompt e a das variantes no anyOf do schema. Com
# exclusao depois de condicao_limiar, o modelo passou a devolver como generico condições por
# limiar que antes reconhecia.
CONSTRUTOS_HABILITADOS: dict[str, Construto] = {
    "bonus_fixo": BONUS_FIXO,
    "exclusao": EXCLUSAO,
    "condicao_limiar": Construto(
        propriedades=condicao_limiar.PROPRIEDADES,
        obrigatorios=condicao_limiar.OBRIGATORIOS,
        instrucoes=INSTRUCOES_CONDICAO_LIMIAR,
        converter=condicao_limiar.converter,
        lastro_no_trecho=True,
    ),
}
