"""Do julgamento à linha de `resultados_simulacao` e ao evento `simulacao-concluida` (T-067).

Funções puras: nada aqui toca o banco nem o broker. A linha e o evento saem da mesma forma
(`ResultadoGravado`), tanto para o resultado recém-gravado quanto para o que uma reentrega
encontra já gravado, então os dois caminhos publicam exatamente a mesma coisa.

Um `erro_codigo` leva na linha o diagnóstico da falha (T-204): a causa classificada e, quando
existirem, a falha que o sandbox capturou, os problemas de schema e os elementos que a conferência
de cobertura reprovou (T-241). O evento continua só com a referência; quem precisa do diagnóstico
o lê da linha pelo `resultado_id`.
"""

from dataclasses import dataclass, field
from typing import Any, NotRequired, TypedDict

from app.execucao.coleta import Motivo
from app.execucao.schema import Problema, validar_diagnostico
from app.execucao.veredito import Julgamento
from app.mensageria.contracts import SimulacaoConcluida
from app.repositorio.resultados import ResultadoGravado
from app.sandbox.envelope import Falha


class Diagnostico(TypedDict):
    """`resultado-diagnostico.schema.json`: por que um `erro_codigo` falhou.

    A causa é a classificação do worker. A falha e os problemas vêm do container e são dado não
    confiável: vão para a linha, nunca para um log nem para o evento.
    """

    causa: Motivo
    # Só quando o sandbox capturou uma exceção: timeout, memória e saída inválida não têm uma,
    # e nenhuma é inventada para eles.
    falha: NotRequired[Falha]
    # Só quando o resultado saiu do schema.
    problemas: NotRequired[list[Problema]]
    # Só com a cobertura incompleta, e cada lista só quando tem item: os elementos exigidos que o
    # código não declarou, e os que receberam contribuição sem ser exigidos.
    elementos_ausentes: NotRequired[list[str]]
    elementos_fora_da_regra: NotRequired[list[str]]


class DiagnosticoForaDoContratoError(ValueError):
    """O diagnóstico montado não valida contra o schema: é erro do worker, nunca da regra."""

    def __init__(self, problemas: list[Problema]) -> None:
        super().__init__("diagnóstico fora de resultado-diagnostico.schema.json")
        self.problemas = problemas


@dataclass(frozen=True)
class LinhaDoResultado:
    """As colunas de `resultados_simulacao` que o worker escreve (além de job e código)."""

    status: str
    veredito: str | None
    totais: dict[str, Any] | None
    assercoes: list[Any]
    decomposicao: dict[str, Any] | None
    # Só em `erro_codigo`; o conteúdo vindo do container fica fora do `repr`, como no desfecho.
    diagnostico: Diagnostico | None = field(repr=False)


def diagnostico_do_julgamento(julgamento: Julgamento) -> Diagnostico | None:
    """O diagnóstico de um `erro_codigo`, validado contra o contrato; nulo nos demais desfechos.

    A falha é a que o sandbox escreveu no envelope, conservada como veio. Um diagnóstico que não
    valida levanta `DiagnosticoForaDoContratoError` em vez de ser gravado pela metade.
    """
    if julgamento.classe != "erro_codigo":
        return None
    diagnostico = Diagnostico(causa=julgamento.motivo)
    desfecho = julgamento.desfecho
    if desfecho is not None and desfecho.erro is not None:
        diagnostico["falha"] = desfecho.erro
    if desfecho is not None and desfecho.problemas:
        diagnostico["problemas"] = list(desfecho.problemas)
    cobertura = julgamento.cobertura
    if cobertura is not None and cobertura.ausentes:
        diagnostico["elementos_ausentes"] = list(cobertura.ausentes)
    if cobertura is not None and cobertura.fora_da_regra:
        diagnostico["elementos_fora_da_regra"] = list(cobertura.fora_da_regra)
    problemas = validar_diagnostico(diagnostico)
    if problemas:
        raise DiagnosticoForaDoContratoError(problemas)
    return diagnostico


def linha_do_julgamento(julgamento: Julgamento) -> LinhaDoResultado:
    """`sucesso` grava o resultado inteiro, com `totais.orcamento` e o veredito quando o comando
    trouxe orçamento, e sem os dois quando não trouxe (T-281); qualquer outro desfecho grava só o
    status e as asserções, e o resto nulo (`assercoes` é `[]` em `erro_infra`), com exceção do
    diagnóstico de um `erro_codigo`.

    O `indeterminado` interno **nunca** é gravado: `resultados_simulacao.veredito` e o evento o
    declaram nulo/ausente fora de `sucesso`, e a api lê `sucesso` + `indeterminado` como um
    número confiável ainda sem julgamento.
    """
    if julgamento.classe != "sucesso":
        desfecho = julgamento.desfecho
        return LinhaDoResultado(
            status=julgamento.classe,
            veredito=None,
            totais=None,
            assercoes=list(desfecho.assercoes) if desfecho is not None else [],
            decomposicao=None,
            diagnostico=diagnostico_do_julgamento(julgamento),
        )

    resultado = julgamento.resultado
    if resultado is None or julgamento.veredito == "indeterminado":
        raise ValueError(
            "um sucesso precisa de resultado e de veredito viavel, inviavel ou ausente"
        )
    return LinhaDoResultado(
        status="sucesso",
        veredito=julgamento.veredito,
        totais=dict(resultado["totais"]),
        assercoes=list(resultado["assercoes"]),
        decomposicao=dict(resultado["decomposicao"]),
        diagnostico=None,
    )


def evento_de(gravado: ResultadoGravado) -> SimulacaoConcluida:
    """O evento do schema: referência, status e, só em `sucesso`, o veredito e os agregados. O
    veredito nulo de um sucesso sem orçamento sai ausente do evento, não `null`.

    A meta e o propósito saem em qualquer status, porque a api separa a execução candidata da
    busca da meta antes de olhar o desfecho (T-270, T-274). A meta, quando a execução teve meta;
    o propósito, só quando é `busca_meta`, já que ausente equivale a `simulacao`.

    Claim-check: a decomposição e o desfecho das asserções ficam na linha, não no evento.
    """
    campos: dict[str, Any] = {
        "job_id": gravado.job_id,
        "resultado_id": gravado.id,
        "status": gravado.status,
    }
    if gravado.meta_venda is not None:
        campos["meta_venda"] = gravado.meta_venda
    if gravado.proposito != "simulacao":
        campos["proposito"] = gravado.proposito
    if gravado.status == "sucesso" and gravado.totais is not None:
        totais = gravado.totais
        campos |= {
            "veredito": gravado.veredito,
            "total_baseline": totais["baseline"],
            "total_simulado": totais["simulado"],
            "diferenca_abs": totais["diferenca_abs"],
            "diferenca_pct": totais["diferenca_pct"],
        }
    # A validação do pydantic é a do vocabulário: uma linha com status ou veredito fora do
    # schema não vira evento.
    return SimulacaoConcluida.model_validate(campos)
