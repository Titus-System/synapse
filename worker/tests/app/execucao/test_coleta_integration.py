"""A classificação do desfecho contra a imagem real (T-065).

`test_coleta.py` prova cada linha da tabela com saídas montadas à mão. Aqui a saída vem de um
container de verdade, pela mesma função que o worker usa: o que se afirma é que o harness
real e o classificador concordam, e que cada classe dos critérios de aceitação sai de um
código que faz aquilo mesmo.
"""

import json
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.execucao.baseline import carregar_baselines
from app.execucao.coleta import DesfechoClassificado, classificar, classificar_falha_de_infra
from app.execucao.container import Limites, SaidaBruta, SandboxInfraError, executar_no_sandbox
from app.execucao.preparo import PayloadContainer, preparar_execucao
from app.execucao.veredito import julgar
from app.mensageria.contracts import ExecutarCodigo
from app.repositorio.codigos_gerados import CodigoGerado
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


# ---- o julgamento (T-066) com o harness real ----


def julgar_2025_11(desfecho: DesfechoClassificado, orcamento: float) -> Any:
    return julgar(desfecho, ["2025-11"], orcamento, carregar_baselines())


def test_o_total_do_container_e_o_baseline_congelado_do_worker(imagem: str) -> None:
    """A conferência precisa concordar com o harness real, centavo a centavo e fração a fração:
    se divergisse por arredondamento, todo job legítimo viraria `baseline_divergente`."""
    _, desfecho = executar_e_classificar(EXEMPLO, imagem)
    assert desfecho.classe == "sucesso"

    julgamento = julgar_2025_11(desfecho, 999999999.0)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "sucesso",
        "ok",
        "viavel",
    )
    assert julgamento.totais is not None
    assert julgamento.totais["baseline"] == BASELINE_2025_11


def test_o_veredito_com_o_total_real_no_limite_do_orcamento(imagem: str) -> None:
    """DEC-093 com o número que o harness produziu, e não um escolhido para o teste: orçamento
    igual ao total simulado é viável, e um centavo abaixo dele, inviável."""
    _, desfecho = executar_e_classificar(EXEMPLO, imagem)
    assert desfecho.resultado is not None
    simulado = desfecho.resultado["totais"]["simulado"]

    assert julgar_2025_11(desfecho, simulado).veredito == "viavel"
    assert julgar_2025_11(desfecho, round(simulado + 0.01, 2)).veredito == "viavel"
    assert julgar_2025_11(desfecho, round(simulado - 0.01, 2)).veredito == "inviavel"


def test_a_diferenca_do_container_e_a_do_baseline_do_worker(imagem: str) -> None:
    _, desfecho = executar_e_classificar(EXEMPLO, imagem)

    julgamento = julgar_2025_11(desfecho, 999999999.0)

    assert julgamento.totais is not None
    totais = julgamento.totais
    assert round(totais["simulado"] - totais["baseline"], 2) == totais["diferenca_abs"]
    assert totais["diferenca_pct"] == pytest.approx(totais["diferenca_abs"] / BASELINE_2025_11)


# O harness guarda o baseline em registros Python que a regra nunca recebe (T-033). Mas a regra
# roda no mesmo processo: o gc entrega esses registros, e ela infla o baseline em 10% sem tocar
# em nada que recebeu. A diferença some para o outro lado (o simulado passa a ser 10% "menor"),
# a decomposição reconcilia e nenhuma invariante é violada: uma economia inventada, com tudo em
# ordem, que só a comparação com o baseline que o worker leu por conta própria denuncia.
REGRA_QUE_INFLA_O_BASELINE_DO_HARNESS = """
import gc
def aplicar_regra(bases, apuracao_base, competencias):
    alvo = None
    for objeto in gc.get_objects():
        if (isinstance(objeto, tuple) and len(objeto) == len(apuracao_base) and objeto
                and isinstance(objeto[0], dict) and "comissao" in objeto[0]
                and "cod_marca" in objeto[0]):
            alvo = objeto
            break
    if alvo is None:
        raise RuntimeError("baseline do harness não encontrado")
    inflado = {}
    for registro in alvo:
        registro["comissao"] = round(registro["comissao"] * 1.10, 2)
        inflado[(registro["matricula"], registro["competencia"])] = registro["comissao"]
    contribuicoes = apuracao_base[
        ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]
    ].copy()
    contribuicoes["elemento_ref"] = "elem.1"
    contribuicoes["delta"] = [
        round(linha.comissao - inflado[(linha.matricula, linha.competencia)], 2)
        for linha in apuracao_base.itertuples()
    ]
    return {"apuracao_simulada": apuracao_base.copy(), "contribuicoes": contribuicoes}
"""


def test_regra_que_infla_o_baseline_do_harness_e_denunciada_pelo_worker(imagem: str) -> None:
    _, desfecho = executar_e_classificar(REGRA_QUE_INFLA_O_BASELINE_DO_HARNESS, imagem)

    # Controle: para o harness e para a classificação isto é um sucesso. Sem a conferência do
    # worker, a "economia" de 10% seguiria para o usuário como número confiável. Se o harness
    # for endurecido e este assert cair, o ataque deixou de existir por este caminho: adapte
    # o teste, não relaxe a conferência.
    assert (desfecho.classe, desfecho.motivo) == ("sucesso", "ok")
    assert desfecho.resultado is not None
    assert desfecho.resultado["totais"]["baseline"] > BASELINE_2025_11
    assert desfecho.resultado["totais"]["diferenca_abs"] < 0

    julgamento = julgar_2025_11(desfecho, 999999999.0)

    assert (julgamento.classe, julgamento.motivo, julgamento.veredito) == (
        "erro_codigo",
        "baseline_divergente",
        "indeterminado",
    )
    assert julgamento.resultado is None


# ---- o container não recebe o orçamento, em forma nenhuma ----

ORCAMENTO_SENTINELA = 487123.45

# Procura o sentinela em todo o processo do container: ambiente, argumentos, linha de comando e
# o conteúdo de todo objeto que o coletor de lixo conhece (o que o harness leu do stdin
# inclusive), como float, Decimal, texto e bytes, em quatro grafias. As formas são montadas em
# tempo de execução: uma constante `"487123.45"` na própria sonda se acharia a si mesma.
SONDA_DE_ORCAMENTO = """
import gc, json, os, sys
from decimal import Decimal

def aplicar_regra(bases, apuracao_base, competencias):
    formas = ["".join(["487123", ".45"]), "".join(["48712", "345"]),
              "".join(["487123", ",45"]), "".join(["487123", ".4"])]
    numero = float("".join(["487123", ".45"]))
    decimal = Decimal("".join(["487123", ".45"]))
    proprios = {id(x) for x in formas} | {id(numero), id(decimal)}
    achados = []

    def confere(origem, valor):
        if id(valor) in proprios:
            return
        if isinstance(valor, str) and any(f in valor for f in formas):
            achados.append(origem)
        elif isinstance(valor, bytes) and any(f.encode() in valor for f in formas):
            achados.append(origem)
        elif isinstance(valor, float) and valor == numero:
            achados.append(origem)
        elif isinstance(valor, Decimal) and valor == decimal:
            achados.append(origem)

    guardado = []
    #PLANTAR
    for chave, valor in os.environ.items():
        confere("environ", chave)
        confere("environ", valor)
    for argumento in sys.argv:
        confere("argv", argumento)
    with open("/proc/self/cmdline", "rb") as arquivo:
        confere("cmdline", arquivo.read())
    for objeto in gc.get_objects():
        if isinstance(objeto, dict):
            itens = list(objeto.keys()) + list(objeto.values())
        elif isinstance(objeto, (list, tuple, set, frozenset)):
            itens = list(objeto)
        else:
            continue
        for item in itens:
            confere("objeto", item)
    print("SONDA " + json.dumps(sorted(set(achados))), file=sys.stderr, flush=True)
    raise RuntimeError("a sonda terminou")
"""

# O controle: o sentinela existe de propósito num objeto vivo do container, e a sonda tem de
# achá-lo. Sem isso, uma sonda quebrada relataria "nada" e o teste passaria pelo motivo errado.
PLANTA = 'guardado.append("".join(["487123", ".45"]))'


def achados_da_sonda(saida: SaidaBruta) -> list[str]:
    linhas = [t for t in saida.stderr.decode().splitlines() if t.startswith("SONDA ")]
    assert len(linhas) == 1, f"a sonda não relatou: {saida.stderr[-500:]!r}"
    return list(json.loads(linhas[0].removeprefix("SONDA ")))


def execucao_com_orcamento(fonte: str) -> Any:
    """O caminho do consumidor até o container: o comando com o orçamento, o código lido do
    banco, e `preparar_execucao` separando os dois."""
    job_id, codigo_id = uuid4(), uuid4()
    comando = ExecutarCodigo(
        job_id=job_id,
        codigo_gerado_id=codigo_id,
        competencias=["2025-11"],
        orcamento=ORCAMENTO_SENTINELA,
    )
    codigo = CodigoGerado(id=codigo_id, job_id=job_id, linguagem="python", fonte=fonte)
    return preparar_execucao(comando, codigo)


def test_a_sonda_de_orcamento_enxerga_o_sentinela_quando_ele_existe(imagem: str) -> None:
    execucao = execucao_com_orcamento(SONDA_DE_ORCAMENTO.replace("#PLANTAR", PLANTA))

    saida = executar_no_sandbox(execucao.payload, imagem=imagem, limites=CURTO)

    assert achados_da_sonda(saida) == ["objeto"]


def test_o_container_nao_recebe_o_orcamento_em_nenhuma_forma(imagem: str) -> None:
    execucao = execucao_com_orcamento(SONDA_DE_ORCAMENTO)
    assert execucao.orcamento == ORCAMENTO_SENTINELA

    saida = executar_no_sandbox(execucao.payload, imagem=imagem, limites=CURTO)

    assert achados_da_sonda(saida) == []
