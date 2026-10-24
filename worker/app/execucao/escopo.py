"""Conferência de escopo: fora do alcance da regra, a comissão simulada é a do baseline.

O codegen calcula o alcance a partir da representação da regra e o envia no comando: a vigência,
os filtros de loja, marca e cargo e as exclusões. O código gerado pode rodar, passar nas asserções
e na cobertura e ainda assim mudar a comissão de quem a regra não alcança, como um bônus pago em
toda loja. Aqui, no processo do worker e linha a linha do detalhamento, essa mudança vira
`erro_codigo` com causa `fora_do_escopo`, que o codegen devolve ao modelo para correção.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import TypedDict

from app.mensageria.contracts import AlcanceDaRegra
from app.sandbox.regras_base import CENTAVO
from app.sandbox.resultado import LinhaDetalhada, LinhasResultado

#: Quantas linhas o diagnóstico mostra: bastam para o modelo ver onde mudou, e o total diz o resto.
EXEMPLOS = 5


class LinhaForaDoEscopo(TypedDict):
    """Item de `linhas_fora_do_escopo.exemplos` em `resultado-diagnostico.schema.json`."""

    competencia: str
    matricula: str
    cod_loja: str
    cod_marca: str
    cod_cargo: str
    diferenca: float


@dataclass(frozen=True)
class ForaDoEscopo:
    """As linhas fora do alcance com a comissão mudada: quantas e as primeiras, na ordem do
    detalhamento. Os exemplos vêm do container e ficam fora do ``repr``."""

    total: int
    exemplos: tuple[LinhaForaDoEscopo, ...]

    def __repr__(self) -> str:
        return f"ForaDoEscopo(total={self.total})"


def alcanca(alcance: AlcanceDaRegra, competencia: str, linha: LinhaDetalhada) -> bool:
    """A linha está no alcance quando atende a todo filtro presente e não foi excluída."""
    if alcance.vigencia is not None and not (
        alcance.vigencia.inicio <= competencia <= alcance.vigencia.fim
    ):
        return False
    da_linha = {
        "loja": str(linha["cod_loja"]),
        "marca": str(linha["cod_marca"]),
        "cargo": str(linha["cod_cargo"]),
    }
    filtros = {"loja": alcance.loja, "marca": alcance.marca, "cargo": alcance.cargo}
    if any(
        codigos is not None and da_linha[dimensao] not in codigos
        for dimensao, codigos in filtros.items()
    ):
        return False
    excluidos = alcance.excluidos
    if excluidos is None:
        return True
    excluidas = {"loja": excluidos.loja, "marca": excluidos.marca, "cargo": excluidos.cargo}
    return not any(
        codigos is not None and da_linha[dimensao] in codigos
        for dimensao, codigos in excluidas.items()
    )


def conferir_escopo(alcance: AlcanceDaRegra, linhas: LinhasResultado) -> ForaDoEscopo | None:
    """None quando toda linha fora do alcance conserva a comissão do baseline.

    A tolerância é de um centavo, a mesma da conciliação das contribuições: o código que reapura
    a linha do baseline pode arredondar de outro jeito sem ter mudado a regra.
    """
    exemplos: list[LinhaForaDoEscopo] = []
    total = 0
    for competencia, colaboradores in linhas.items():
        for matricula, linha in colaboradores.items():
            if alcanca(alcance, competencia, linha):
                continue
            diferenca = Decimal(str(linha["comissao_simulada"])) - Decimal(
                str(linha["comissao_baseline"])
            )
            if abs(diferenca) <= CENTAVO:
                continue
            total += 1
            if len(exemplos) < EXEMPLOS:
                exemplos.append(
                    LinhaForaDoEscopo(
                        competencia=competencia,
                        matricula=matricula,
                        cod_loja=str(linha["cod_loja"]),
                        cod_marca=str(linha["cod_marca"]),
                        cod_cargo=str(linha["cod_cargo"]),
                        diferenca=float(diferenca),
                    )
                )
    if total == 0:
        return None
    return ForaDoEscopo(total=total, exemplos=tuple(exemplos))
