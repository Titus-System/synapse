import re
from collections.abc import Sequence
from contextlib import suppress
from copy import deepcopy
from typing import Any

import simplejson
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as ErroSchema
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from app.extracao.escopo import conferir_escopo_universal
from app.extracao.lastro import (
    conferir_numero,
    conferir_periodo,
    normalizar,
    restaurar_trechos_literais,
)
from app.extracao.modelos import (
    ChamadaExtracao,
    FalhaExtracaoError,
    MotivoRebaixamento,
    Rebaixamento,
    ResultadoExtracao,
)
from app.extracao.montagem import consumo_de_tokens, montar_elemento, objeto_sem_duplicatas
from app.extracao.parametros import validar_parametros
from app.extracao.registro import CONSTRUTOS_HABILITADOS
from app.extracao.schema import schema_envelope, schema_saida
from app.extracao.taxas import conferir_taxa_por_cargo
from app.extracao.vocabulario import carregar_vocabulario, resolver_codigo
from app.graph.prompts.extraction import montar_prompt_extracao
from app.representacao_regra import RepresentacaoRegra
from app.resposta_modelo import extrair_resposta
from app.tipos_estado import ValorRegra

# Como o texto enuncia uma taxa do núcleo além dos trechos que o núcleo cita: conectivos, o nome
# da taxa e a base de vendas. A lista é fechada: qualquer outra palavra, ou um número que o núcleo
# não cita, mantém o elemento.
_PALAVRAS_DO_NUCLEO = frozenset(
    {
        "a", "o", "as", "os", "ao", "aos", "de", "da", "do", "das", "dos", "em", "na", "no",
        "nas", "nos", "e", "com", "para", "por", "sobre", "um", "uma", "sua", "suas", "seu",
        "seus", "somente", "apenas", "regra", "vale", "comissao", "comissoes", "taxa",
        "percentual", "cento", "venda", "vendas",
    }
)  # fmt: skip
_VENDA_INDIVIDUAL = frozenset({"individual", "individuais"})
# A geração calcula a taxa do gerente sobre a venda total da loja, e as dos demais cargos sobre a
# venda individual.
_CARGO_GERENTE = "150"


def _so_enuncia_o_nucleo(
    texto: str, trechos_do_nucleo: Sequence[str], palavras: frozenset[str]
) -> bool:
    restante = normalizar(texto)
    citou = False
    for trecho in sorted({normalizar(t) for t in trechos_do_nucleo} - {""}, key=len, reverse=True):
        restante, ocorrencias = re.subn(rf"\b{re.escape(trecho)}\b", " ", restante)
        citou = citou or ocorrencias > 0
    return citou and set(restante.split()) <= palavras


def _repete_o_nucleo(
    elemento: dict[str, Any], trechos_do_nucleo: Sequence[str], nucleo: dict[str, ValorRegra]
) -> bool:
    """O genérico que só reescreve o que o núcleo já tem, apesar de o prompt proibir a repetição.

    O código gerado implementa o núcleo e não teria o que declarar para o elemento, então a
    conferência de cobertura reprovaria a simulação. A venda individual só repete a base do núcleo
    quando o gerente está fora do escopo.
    """
    if elemento.get("construto_pretendido") != "generico":
        return False
    trecho, descricao = elemento.get("trecho"), elemento.get("descricao")
    if not isinstance(trecho, str) or not isinstance(descricao, str):
        return False
    cargos = nucleo.get("cargo")
    individual = isinstance(cargos, list) and bool(cargos) and _CARGO_GERENTE not in cargos
    palavras = _PALAVRAS_DO_NUCLEO | _VENDA_INDIVIDUAL if individual else _PALAVRAS_DO_NUCLEO
    return all(_so_enuncia_o_nucleo(t, trechos_do_nucleo, palavras) for t in (trecho, descricao))


def _montar(
    conteudo: str, texto: str, competencias: Sequence[str]
) -> tuple[RepresentacaoRegra, list[Rebaixamento], dict[str, ValorRegra], int]:
    rascunho = simplejson.loads(
        conteudo, use_decimal=True, allow_nan=False, object_pairs_hook=objeto_sem_duplicatas
    )
    Draft202012Validator(schema_envelope()).validate(rascunho)
    restaurar_trechos_literais(rascunho, texto)

    nucleo: dict[str, ValorRegra] = {}
    # Os trechos de cada campo aceito no núcleo, para reconhecer o elemento que só os repete.
    trechos: dict[str, list[str]] = {}
    rebaixamentos_do_nucleo: list[Rebaixamento] = []
    rascunho_nucleo = rascunho["nucleo"]
    if "percentual" in rascunho_nucleo:
        campo = rascunho_nucleo["percentual"]
        if conferir_numero(texto, campo["trecho"], campo["valor"], percentual=True):
            nucleo["percentual"] = campo["valor"]
            trechos["percentual"] = [campo["trecho"]]

    def rebaixar_nucleo(campo: str, motivo: MotivoRebaixamento) -> None:
        # O critério não reconhecido não vira elemento genérico: o código gerado não teria o
        # que implementar, e a simulação pararia na conferência de cobertura. O registro faz a
        # validação pedir a correção dele.
        referencia = f"nucleo.{campo}"
        if all(rebaixamento.ref != referencia for rebaixamento in rebaixamentos_do_nucleo):
            rebaixamentos_do_nucleo.append(Rebaixamento(ref=referencia, motivo=motivo))

    if "vigencia" in rascunho_nucleo:
        campo = rascunho_nucleo["vigencia"]
        confere, resolvido = conferir_periodo(
            texto, campo["trecho"], campo["valor"], competencias, vigencia=True
        )
        if confere:
            nucleo["vigencia"] = campo["valor"]
            trechos["vigencia"] = [campo["trecho"]]
        else:
            rebaixar_nucleo(
                "vigencia", "periodo_nao_resolvido" if not resolvido else "valor_sem_lastro"
            )

    for nome in ("loja", "marca", "cargo"):
        if nome not in rascunho_nucleo:
            continue
        escopo = rascunho_nucleo[nome]
        if isinstance(escopo, dict):
            if conferir_escopo_universal(nome, escopo["trecho"], texto):
                nucleo[nome] = []
                trechos[nome] = [escopo["trecho"]]
            else:
                rebaixar_nucleo(nome, "valor_sem_lastro")
            continue
        aprovados: list[ValorRegra] = []
        for campo in rascunho_nucleo[nome]:
            codigo, motivo = resolver_codigo(nome, campo["valor"], campo["trecho"], texto)
            if codigo is not None:
                trechos.setdefault(nome, []).append(campo["trecho"])
                if codigo not in aprovados:
                    aprovados.append(codigo)
            else:
                assert motivo is not None
                rebaixar_nucleo(nome, motivo)
        if aprovados:
            nucleo[nome] = aprovados

    if "taxas_por_cargo" in rascunho_nucleo:
        taxas: list[ValorRegra] = []
        cargos: list[ValorRegra] = []
        falhas: list[MotivoRebaixamento | None] = []
        for campo in rascunho_nucleo["taxas_por_cargo"]:
            taxa, motivo = conferir_taxa_por_cargo(campo, texto)
            if "percentual" in rascunho_nucleo and not re.search(
                r"\b(exceto|excecao|salvo)\b", normalizar(campo["trecho"])
            ):
                taxa, motivo = None, "termo_ambiguo"
            if taxa is None:
                assert motivo is not None
            else:
                if taxa not in taxas:
                    taxas.append(taxa)
                if taxa["cargo"] not in cargos:
                    cargos.append(taxa["cargo"])
            falhas.append(motivo)
        # Não aplicar só os pares reconhecidos de uma proposta parcialmente resolvida.
        if not any(falhas):
            nucleo["taxas_por_cargo"] = taxas
            trechos["taxas_por_cargo"] = [
                campo["trecho"] for campo in rascunho_nucleo["taxas_por_cargo"]
            ]
            if "cargo" not in rascunho_nucleo:
                nucleo["cargo"] = cargos
        else:
            rebaixar_nucleo("taxas_por_cargo", next(falha for falha in falhas if falha))
            nucleo.pop("percentual", None)

    trechos_do_nucleo = [t for campo, lista in trechos.items() if campo in nucleo for t in lista]
    elementos: list[dict[str, ValorRegra]] = []
    rebaixamentos: list[Rebaixamento] = []
    redundantes = 0
    for elemento in rascunho["elementos"]:
        if _repete_o_nucleo(elemento, trechos_do_nucleo, nucleo):
            redundantes += 1
            continue
        ref = f"elem.{len(elementos) + 1}"
        convertido, rebaixamento = montar_elemento(elemento, ref, texto, competencias)
        elementos.append(convertido)
        if rebaixamento is not None:
            rebaixamentos.append(rebaixamento)
    rebaixamentos.extend(rebaixamentos_do_nucleo)

    representacao = RepresentacaoRegra.model_validate(
        {"nucleo": nucleo, "especificacoes": elementos}
    )
    parametros_brutos: dict[str, ValorRegra] = {}
    for nome, campo in rascunho["parametros"].items():
        if nome == "competencias":
            confere, resolvido = conferir_periodo(
                texto, campo["trecho"], campo["valor"], competencias, vigencia=False
            )
        else:
            confere = conferir_numero(texto, campo["trecho"], campo["valor"], percentual=False)
            resolvido = True
        if confere:
            parametros_brutos[nome] = campo["valor"]
        else:
            rebaixamentos.append(
                Rebaixamento(
                    ref=f"parametros.{nome}",
                    motivo="periodo_nao_resolvido" if not resolvido else "valor_sem_lastro",
                )
            )
    parametros = validar_parametros(parametros_brutos)
    return representacao, rebaixamentos, parametros, redundantes


async def extrair_regra(
    texto: str,
    competencias: Sequence[str],
    *,
    modelo: BaseChatModel,
    metadados_modelo: dict[str, Any],
) -> ResultadoExtracao:
    if not texto.strip():
        raise FalhaExtracaoError("Texto de entrada vazio")
    schema = schema_saida(CONSTRUTOS_HABILITADOS)
    prompt = montar_prompt_extracao(
        texto,
        competencias,
        schema,
        [c.instrucoes for c in CONSTRUTOS_HABILITADOS.values()],
        carregar_vocabulario(),
    )
    resposta = await modelo.ainvoke(
        [HumanMessage(content=prompt)],
        response_mime_type="application/json",
        response_json_schema=schema,
    )
    conteudo, motivo = extrair_resposta(resposta)
    if not conteudo.strip() or motivo != "STOP":
        raise FalhaExtracaoError("Resposta vazia, bloqueada ou interrompida")

    montado = None
    with suppress(ValueError, TypeError, ErroSchema, ValidationError, RecursionError):
        montado = _montar(conteudo, texto, competencias)
    # Fora do except para a exceção pública não reter o JSON em __context__.
    if montado is None:
        raise FalhaExtracaoError("Resposta incompatível com o schema de extração")

    representacao, rebaixamentos, parametros, redundantes = montado
    return ResultadoExtracao(
        representacao=representacao,
        rebaixamentos=rebaixamentos,
        parametros=parametros,
        elementos_redundantes=redundantes,
        chamada=ChamadaExtracao(
            prompt=prompt,
            resposta=conteudo,
            modelo=deepcopy(metadados_modelo),
            consumo_tokens=consumo_de_tokens(resposta),
        ),
    )
