"""As linhas a que uma regra dá efeito, pela vigência, pelo escopo e pelas exclusões.

Fora delas, a comissão de cada matrícula e competência é a do baseline. A sugestão de taxa usa
isso para separar a parte da comissão que nenhuma taxa move, e o comando `executar-codigo` leva o
alcance ao worker, que recusa como `fora_do_escopo` o resultado que muda uma linha fora dele.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.tipos_estado import ValorRegra

_DIMENSOES = ("loja", "marca", "cargo")


@dataclass(frozen=True, slots=True)
class AlcanceDaRegra:
    """A regra não alcança a linha fora da vigência, fora dos filtros de loja, marca e cargo do
    núcleo, nem a excluída por uma exclusão. Sem taxa uniforme, também não alcança o cargo sem
    taxa própria, que o contrato do núcleo manda conservar no baseline. Filtro vazio ou ausente não
    restringe a dimensão.
    """

    vigencia: tuple[str, str] | None
    filtros: Mapping[str, frozenset[str]]
    cargos_com_taxa: frozenset[str] | None
    excluidos: Mapping[str, frozenset[str]]

    @classmethod
    def da(cls, representacao: Mapping[str, ValorRegra]) -> "AlcanceDaRegra":
        nucleo = representacao.get("nucleo")
        if not isinstance(nucleo, Mapping):
            return cls(None, {}, None, {})
        vigencia = nucleo.get("vigencia")
        inicio = vigencia.get("inicio") if isinstance(vigencia, Mapping) else None
        fim = vigencia.get("fim") if isinstance(vigencia, Mapping) else None
        filtros = {
            dimensao: frozenset(str(codigo) for codigo in codigos)
            for dimensao in _DIMENSOES
            if isinstance(codigos := nucleo.get(dimensao), list) and codigos
        }
        por_cargo = nucleo.get("taxas_por_cargo")
        cargos_com_taxa = (
            frozenset(str(par.get("cargo")) for par in por_cargo if isinstance(par, Mapping))
            if isinstance(por_cargo, list) and not _e_numero(nucleo.get("percentual"))
            else None
        )
        excluidos: dict[str, frozenset[str]] = {}
        especificacoes = representacao.get("especificacoes")
        for elemento in especificacoes if isinstance(especificacoes, list) else []:
            if (
                isinstance(elemento, Mapping)
                and elemento.get("construto") == "exclusao"
                and isinstance(dimensao := elemento.get("dimensao"), str)
                and isinstance(valores := elemento.get("valores"), list)
            ):
                excluidos[dimensao] = excluidos.get(dimensao, frozenset()) | {
                    str(valor) for valor in valores
                }
        return cls(
            (inicio, fim) if isinstance(inicio, str) and isinstance(fim, str) else None,
            filtros,
            cargos_com_taxa,
            excluidos,
        )

    def alcanca(self, competencia: str, linha: Mapping[str, object]) -> bool:
        if self.vigencia is not None and not self.vigencia[0] <= competencia <= self.vigencia[1]:
            return False
        if any(
            str(linha.get(f"cod_{dim}")) not in codigos for dim, codigos in self.filtros.items()
        ):
            return False
        if (
            self.cargos_com_taxa is not None
            and str(linha.get("cod_cargo")) not in self.cargos_com_taxa
        ):
            return False
        return not any(
            str(linha.get(f"cod_{dim}")) in valores for dim, valores in self.excluidos.items()
        )

    def para_comando(self) -> dict[str, object] | None:
        """O campo `alcance` de `executar-codigo`, com a mesma decisão de `alcanca`.

        None quando a regra não restringe linha alguma, e também quando nenhum cargo do filtro tem
        taxa própria: a lista vazia não tem forma no contrato, e sem a conferência o worker não
        reprova o que a regra deveria ter feito.
        """
        alcance: dict[str, object] = {}
        if self.vigencia is not None:
            alcance["vigencia"] = {"inicio": self.vigencia[0], "fim": self.vigencia[1]}
        for dimensao in ("loja", "marca"):
            if dimensao in self.filtros:
                alcance[dimensao] = sorted(self.filtros[dimensao])
        cargos = self.filtros.get("cargo")
        if self.cargos_com_taxa is not None:
            cargos = self.cargos_com_taxa if cargos is None else cargos & self.cargos_com_taxa
            if not cargos:
                return None
        if cargos is not None:
            alcance["cargo"] = sorted(cargos)
        excluidos = {
            dimensao: sorted(valores)
            for dimensao, valores in self.excluidos.items()
            if dimensao in _DIMENSOES and valores
        }
        if excluidos:
            alcance["excluidos"] = excluidos
        return alcance or None


def _e_numero(valor: ValorRegra) -> bool:
    return not isinstance(valor, bool) and isinstance(valor, Decimal | int)
