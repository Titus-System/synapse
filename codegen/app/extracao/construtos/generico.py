from app.tipos_estado import ValorRegra


def montar_generico(
    ref: str, descricao: str, campos: dict[str, ValorRegra] | None = None
) -> dict[str, ValorRegra]:
    elemento: dict[str, ValorRegra] = {"ref": ref, "construto": "generico", "descricao": descricao}
    if campos is not None:
        elemento["campos"] = campos
    return elemento
