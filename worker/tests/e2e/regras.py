"""Os códigos gerados que os e2e mandam o worker executar. Cada um é uma regra de verdade, no
formato do contrato da T-034, e roda no container real."""

from tests.app.execucao.test_coleta_integration import REGRA_QUE_INFLA_O_BASELINE_DO_HARNESS
from tests.app.sandbox.test_harness import EXEMPLO

# O exemplo do contrato: apura 494.037,78 sobre o baseline de 508.382,32 de novembro.
SUCESSO = EXEMPLO
SIMULADO_DO_EXEMPLO = 494037.78
BASELINE_2025_11 = 508382.32

# Na meta de venda (T-270): as vendas de novembro somam 13.271.681,51, e a meta é 10% acima. Sobre
# as vendas escaladas, o baseline reapurado é 558.870,26 (não 1,1 vez o congelado), e o exemplo
# apura 543.091,28. Os dois números saem do motor congelado; test_escalonamento.py confere o
# baseline.
VENDAS_2025_11 = 13271681.51
META_2025_11 = 14598849.661
BASELINE_NA_META_2025_11 = 558870.26
SIMULADO_DO_EXEMPLO_NA_META = 543091.28

# Infla em 10% o baseline que o harness guarda, pelo gc: uma economia inventada que só a
# conferência do worker denuncia.
INFLA_O_BASELINE = REGRA_QUE_INFLA_O_BASELINE_DO_HARNESS

# O mesmo exemplo, depois de dormir: dá tempo de matar o worker no meio da execução.
LENTA = (
    EXEMPLO
    + """

_original = aplicar_regra


def aplicar_regra(bases, apuracao_base, competencias):
    import time

    time.sleep(10)
    return _original(bases, apuracao_base, competencias)
"""
)

COMISSAO_NEGATIVA = """
def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    simulada.loc[simulada.index[0], "comissao"] = -1.0
    contribuicoes = simulada.iloc[:1].copy()
    contribuicoes["elemento_ref"] = "elem.1"
    contribuicoes["delta"] = -1.0
    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
"""

# Levanta, escreve no stdout e no stderr, e tem um marcador no próprio código: nada disso pode
# chegar ao log do worker.
LEVANTA_COM_SEGREDOS = """
import sys

# SEGREDO-NA-FONTE
def aplicar_regra(bases, apuracao_base, competencias):
    print("SEGREDO-NO-STDOUT")
    print("SEGREDO-NO-STDERR", file=sys.stderr)
    raise ValueError("SEGREDO-NA-MENSAGEM")
"""

# Não termina: o prazo real é o de 60 s, uma constante do worker.
NAO_TERMINA = """
import time

def aplicar_regra(bases, apuracao_base, competencias):
    time.sleep(600)
"""
