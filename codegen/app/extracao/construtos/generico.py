from app.tipos_estado import ValorRegra


def montar_generico(ref: str, descricao: str) -> dict[str, ValorRegra]:
    return {"ref": ref, "construto": "generico", "descricao": descricao}
