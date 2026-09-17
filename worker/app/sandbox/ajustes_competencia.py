"""Ajustes determinísticos aplicados nas etapas corretas do motor base."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AjusteCompetencia:
    # Base e adicional percentual sofrem as proporções e o piso da T-030.
    base_adicional: Decimal = Decimal(0)
    comissao_adicional: Decimal = Decimal(0)
    # Bônus explicitamente acrescido ao valor final não é proporcionalizado.
    bonus_final: Decimal = Decimal(0)
    origens: tuple[Mapping[str, object], ...] = ()
