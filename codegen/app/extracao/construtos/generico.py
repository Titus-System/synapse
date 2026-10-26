from app.tipos_estado import ValorRegra

# Descrição de um elemento cujo trecho não está no texto: não diz o que a regra faz, então a
# validação pede que o usuário descreva a condição de novo antes da geração.
DESCRICAO_SEM_LASTRO = "Elemento sem lastro verificável"


def montar_generico(
    ref: str, descricao: str, campos: dict[str, ValorRegra] | None = None
) -> dict[str, ValorRegra]:
    elemento: dict[str, ValorRegra] = {"ref": ref, "construto": "generico", "descricao": descricao}
    if campos is not None:
        elemento["campos"] = campos
    return elemento
