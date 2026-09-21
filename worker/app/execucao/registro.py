"""Do julgamento à linha de `resultados_simulacao` e ao evento `simulacao-concluida` (T-067).

Funções puras: nada aqui toca o banco nem o broker. A linha e o evento saem da mesma forma
(`ResultadoGravado`), tanto para o resultado recém-gravado quanto para o que uma reentrega
encontra já gravado, então os dois caminhos publicam exatamente a mesma coisa.
"""

from dataclasses import dataclass
from typing import Any

from app.execucao.veredito import Julgamento
from app.mensageria.contracts import SimulacaoConcluida
from app.repositorio.resultados import ResultadoGravado


@dataclass(frozen=True)
class LinhaDoResultado:
    """As colunas de `resultados_simulacao` que o worker escreve (além de job e código)."""

    status: str
    veredito: str | None
    totais: dict[str, Any] | None
    assercoes: list[Any]
    decomposicao: dict[str, Any] | None


def linha_do_julgamento(julgamento: Julgamento) -> LinhaDoResultado:
    """`sucesso` grava o resultado inteiro, com `totais.orcamento`; qualquer outro desfecho grava
    só o status e as asserções, e o resto nulo (`assercoes` é `[]` em `erro_infra`).

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
        )

    resultado = julgamento.resultado
    if resultado is None or julgamento.veredito == "indeterminado":
        raise ValueError("um sucesso precisa de resultado e de veredito viavel ou inviavel")
    return LinhaDoResultado(
        status="sucesso",
        veredito=julgamento.veredito,
        totais=dict(resultado["totais"]),
        assercoes=list(resultado["assercoes"]),
        decomposicao=dict(resultado["decomposicao"]),
    )


def evento_de(gravado: ResultadoGravado) -> SimulacaoConcluida:
    """O evento do schema: referência, status e, só em `sucesso`, o veredito e os agregados.

    Claim-check: a decomposição e o desfecho das asserções ficam na linha, não no evento.
    """
    campos: dict[str, Any] = {
        "job_id": gravado.job_id,
        "resultado_id": gravado.id,
        "status": gravado.status,
    }
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
