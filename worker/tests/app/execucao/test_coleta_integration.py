"""A classificação do desfecho contra a imagem real (T-065).

`test_coleta.py` prova cada linha da tabela com saídas montadas à mão. Aqui a saída vem de um
container de verdade, pela mesma função que o worker usa: o que se afirma é que o harness
real e o classificador concordam, e que cada classe dos critérios de aceitação sai de um
código que faz aquilo mesmo.
"""

import json
from uuid import UUID, uuid4

import pytest

from app.execucao.coleta import DesfechoClassificado, classificar, classificar_falha_de_infra
from app.execucao.container import Limites, SaidaBruta, SandboxInfraError, executar_no_sandbox
from app.execucao.preparo import PayloadContainer
from tests.app.sandbox.test_harness import EXEMPLO

pytestmark = pytest.mark.docker

CURTO = Limites(timeout_s=20.0)
ORCAMENTO = 485000.0
BASELINE_2025_11 = 508382.32

REGRA_QUE_LEVANTA = "def aplicar_regra(b, a, c):\n    raise ValueError('boom')\n"

REGRA_COM_COMISSAO_NEGATIVA = """
def aplicar_regra(bases, apuracao_base, competencias):
    simulada = apuracao_base.copy()
    simulada.loc[simulada.index[0], "comissao"] = -1.0
    contribuicoes = simulada.iloc[:1].copy()
    contribuicoes["elemento_ref"] = "elem.1"
    contribuicoes["delta"] = -1.0
    return {"apuracao_simulada": simulada, "contribuicoes": contribuicoes}
"""

# Nada é levantado: a saída simplesmente não é a do contrato.
REGRA_FORA_DO_CONTRATO = "def aplicar_regra(bases, apuracao_base, competencias):\n    return 1\n"

# Sai antes de o harness escrever o envelope, com o mesmo código que ele usa para "falhei eu".
REGRA_QUE_SE_FAZ_DE_HARNESS = "import os\nos._exit(1)\n"

# O harness aponta o fd 1 para o stderr e guarda o canal do envelope num descritor duplicado.
# Esta regra o procura tentando escrever em todos, e sai limpo depois de forjar um envelope
# de sucesso que o harness não produziu.
REGRA_QUE_FORJA_O_ENVELOPE = """
import json, os
def aplicar_regra(bases, apuracao_base, competencias):
    envelope = {
        "versao": 1, "job_id": "%(job)s", "codigo_gerado_id": "%(codigo)s",
        "competencias": competencias, "status": "sucesso",
        "assercoes": [], "resultado": {"totais": {"baseline": 1.0}}, "erro": None,
    }
    linha = (json.dumps(envelope) + "\\n").encode()
    for fd in range(3, 32):
        try:
            os.write(fd, linha)
        except OSError:
            pass
    os._exit(0)
"""


def payload(fonte: str, *, job_id: UUID | None = None) -> PayloadContainer:
    return PayloadContainer(
        job_id=job_id or uuid4(),
        codigo_gerado_id=uuid4(),
        linguagem="python",
        fonte=fonte,
        competencias=["2025-11"],
    )


def executar_e_classificar(fonte: str, imagem: str) -> tuple[SaidaBruta, DesfechoClassificado]:
    """A mesma sequência do consumidor: executa, e classifica com o orçamento do comando."""
    entrada = payload(fonte)
    saida = executar_no_sandbox(entrada, imagem=imagem, limites=CURTO)
    return saida, classificar(saida, entrada, ORCAMENTO)


def test_o_exemplo_do_contrato_e_sucesso_e_o_resultado_segue_intacto(imagem: str) -> None:
    saida, desfecho = executar_e_classificar(EXEMPLO, imagem)

    assert (desfecho.classe, desfecho.motivo) == ("sucesso", "ok")
    assert desfecho.resultado == json.loads(saida.stdout)["resultado"]
    assert desfecho.resultado is not None
    assert desfecho.resultado["totais"]["baseline"] == BASELINE_2025_11
    assert "orcamento" not in desfecho.resultado["totais"]
    assert desfecho.saida is saida


def test_excecao_no_codigo_gerado_e_erro_codigo(imagem: str) -> None:
    _, desfecho = executar_e_classificar(REGRA_QUE_LEVANTA, imagem)

    assert (desfecho.classe, desfecho.motivo) == ("erro_codigo", "excecao")
    assert desfecho.erro is not None
    assert (desfecho.erro["tipo"], desfecho.erro["mensagem"]) == ("ValueError", "boom")
    assert desfecho.resultado is None


def test_comissao_negativa_e_assercao_violada_distinta_de_erro_codigo(imagem: str) -> None:
    _, desfecho = executar_e_classificar(REGRA_COM_COMISSAO_NEGATIVA, imagem)

    assert (desfecho.classe, desfecho.motivo) == ("assercao_violada", "assercao")
    assert [(a["nome"], a["resultado"]) for a in desfecho.assercoes] == [
        ("sem_comissao_negativa", "violada")
    ]
    assert desfecho.resultado is None and desfecho.erro is None


def test_saida_fora_do_contrato_e_erro_codigo(imagem: str) -> None:
    _, desfecho = executar_e_classificar(REGRA_FORA_DO_CONTRATO, imagem)

    assert desfecho.classe == "erro_codigo"
    assert desfecho.resultado is None


def test_falha_ao_subir_o_container_e_erro_infra(imagem: str) -> None:
    """A imagem não existe: o container nem chega a ser criado. É o único desfecho que pede
    repetir o comando, e o consumidor o classifica ao capturar esta exceção."""
    with pytest.raises(SandboxInfraError):
        executar_no_sandbox(payload(EXEMPLO), imagem="synapse-sandbox:inexistente", limites=CURTO)

    desfecho = classificar_falha_de_infra()

    assert (desfecho.classe, desfecho.motivo) == ("erro_infra", "infra")


def test_regra_que_se_faz_passar_por_falha_do_harness_e_erro_do_codigo(imagem: str) -> None:
    """O harness sai com 1 quando falha ele mesmo. Uma regra que faz o mesmo com os._exit(1)
    não pode ganhar por isso uma repetição do comando, que é o que erro_infra daria."""
    saida, desfecho = executar_e_classificar(REGRA_QUE_SE_FAZ_DE_HARNESS, imagem)

    assert saida.codigo_saida == 1 and saida.stdout == b""
    assert (desfecho.classe, desfecho.motivo) == ("erro_codigo", "sem_envelope")


def test_regra_que_forja_o_envelope_de_sucesso_nao_e_sucesso(imagem: str) -> None:
    """A regra acha o canal do envelope e escreve nele um sucesso com os ids certos, saindo com
    0: a forma confere e o código de saída também. O resultado forjado não valida no schema, e
    o desfecho é do código, não um sucesso."""
    entrada = payload("")
    fonte = REGRA_QUE_FORJA_O_ENVELOPE % {
        "job": entrada.job_id,
        "codigo": entrada.codigo_gerado_id,
    }
    entrada = PayloadContainer(**{**entrada.__dict__, "fonte": fonte})

    saida = executar_no_sandbox(entrada, imagem=imagem, limites=CURTO)
    desfecho = classificar(saida, entrada, ORCAMENTO)

    assert saida.codigo_saida == 0 and saida.stdout != b""
    assert desfecho.classe == "erro_codigo"
    assert desfecho.motivo in {"envelope_invalido", "resultado_fora_do_schema"}
    assert desfecho.resultado is None
