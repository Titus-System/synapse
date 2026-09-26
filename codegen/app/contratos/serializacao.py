from datetime import datetime
from uuid import UUID

import simplejson

from app.contratos.mensagens import ModeloContrato


def _escalar(valor: object) -> str:
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, datetime):
        return valor.isoformat().replace("+00:00", "Z")
    raise TypeError("Tipo não serializável no contrato")


def serializar(dto: ModeloContrato) -> bytes:
    # Decimal precisa sair como número JSON, sem passar por float ou string.
    return simplejson.dumps(
        dto.model_dump(mode="python", exclude_unset=True, warnings="error"),
        default=_escalar,
        use_decimal=True,
        allow_nan=False,
        ensure_ascii=False,
    ).encode("utf-8")
