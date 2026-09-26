from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field

type Competencia = Annotated[str, Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]
type Origem = Literal["formulario", "voz", "reprocessamento"]
type Veredito = Literal["viavel", "inviavel", "indeterminado"]
type ValorRegra = (
    dict[str, ValorRegra] | list[ValorRegra] | str | int | bool | Decimal | date | None
)


def _recusar_float(valor: object) -> object:
    if isinstance(valor, float):
        raise ValueError("Informe orçamento como Decimal, inteiro ou texto decimal, nunca float")
    return valor


type Orcamento = Annotated[
    Decimal, BeforeValidator(_recusar_float), Field(ge=0, allow_inf_nan=False)
]
