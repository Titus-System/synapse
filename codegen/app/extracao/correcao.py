from collections.abc import Sequence
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Literal, cast

from jsonschema import Draft202012Validator
from pydantic import ConfigDict, TypeAdapter

from app.extracao.construtos.generico import montar_generico
from app.extracao.escopo import conferir_escopo_universal
from app.extracao.lastro import conferir_numero, conferir_periodo, numeros_citados, trecho_literal
from app.extracao.modelos import FalhaExtracaoError, Rebaixamento
from app.extracao.montagem import montar_elemento
from app.extracao.parametros import validar_parametros
from app.extracao.schema_correcao import schema_envelope_correcao, schema_operacao_correcao
from app.extracao.taxas import conferir_taxa_por_cargo
from app.extracao.vocabulario import CampoCodigo, resolver_codigo
from app.representacao_regra import RepresentacaoRegra
from app.tipos_estado import ValorRegra

type MotivoDiagnostico = Literal[
    "operacao_invalida",
    "operacao_sem_trecho",
    "referencia_inexistente",
    "valor_sem_lastro",
    "codigo_fora_do_vocabulario",
    "termo_ambiguo",
    "periodo_nao_resolvido",
]


@dataclass(frozen=True, slots=True)
class DiagnosticoOperacao:
    """Operação que não foi aplicada, sem serialização no contrato de rebaixamentos da extração.

    A regra e os parâmetros ficam como estavam no ponto em que ela seria aplicada.
    """

    indice: int
    motivo: MotivoDiagnostico


type DiagnosticoCorrecao = Rebaixamento | DiagnosticoOperacao
type ResultadoCorrecao = tuple[RepresentacaoRegra, dict[str, ValorRegra], list[DiagnosticoCorrecao]]

_VALOR: TypeAdapter[ValorRegra] = TypeAdapter(ValorRegra, config=ConfigDict(allow_inf_nan=False))


@dataclass(slots=True)
class _Elemento:
    ref_original: str | None
    conteudo: dict[str, ValorRegra]
    rebaixamento: Rebaixamento | None = None


def _conferir(
    campo: str, valor: Any, texto: str, publicadas: Sequence[str], trecho_operacao: str
) -> tuple[object, MotivoDiagnostico | None]:
    """Confere o valor contra o texto da correção como a extração inicial confere (T-210)."""
    if campo in ("loja", "marca", "cargo"):
        if isinstance(valor, dict) or not valor:
            trecho = valor["trecho"] if isinstance(valor, dict) else trecho_operacao
            return (
                ([], None)
                if conferir_escopo_universal(cast(CampoCodigo, campo), trecho, texto)
                else (None, "valor_sem_lastro")
            )
        # Tudo ou nada: aplicar só os códigos resolvidos encolheria o escopo sem o usuário pedir.
        codigos: list[str] = []
        for item in valor:
            codigo, falha = resolver_codigo(
                cast(CampoCodigo, campo), item["valor"], item["trecho"], texto
            )
            if codigo is None:
                return None, falha
            if codigo not in codigos:
                codigos.append(codigo)
        return codigos, None
    bruto, trecho = valor["valor"], valor["trecho"]
    if campo in ("vigencia", "competencias"):
        confere, resolvido = conferir_periodo(
            texto, trecho, bruto, publicadas, vigencia=campo == "vigencia"
        )
        if not confere:
            return None, "valor_sem_lastro" if resolvido else "periodo_nao_resolvido"
        return bruto, None
    if not conferir_numero(texto, trecho, bruto, percentual=campo == "percentual"):
        return None, "valor_sem_lastro"
    return bruto, None


def _montar_elemento_correcao(
    elemento: dict[str, Any],
    trecho: str,
    texto: str,
    publicadas: Sequence[str],
    *,
    elemento_atual: dict[str, ValorRegra] | None = None,
) -> tuple[dict[str, ValorRegra], Rebaixamento | None]:
    """Nunca transfere números inventados em uma paráfrase para o elemento genérico."""
    descricao = elemento.get("descricao")
    descricao_atual = elemento_atual.get("descricao") if elemento_atual else None
    numeros_atuais = numeros_citados(descricao_atual) if isinstance(descricao_atual, str) else set()
    if isinstance(descricao, str) and not numeros_citados(descricao).issubset(
        numeros_citados(texto) | numeros_atuais
    ):
        return montar_generico("elem.1", trecho), Rebaixamento(
            "elem.1", "valor_sem_lastro", elemento.get("construto_pretendido")
        )
    convertido, rebaixamento = montar_elemento(
        elemento, "elem.1", texto, publicadas, elemento_atual=elemento_atual
    )
    if rebaixamento is not None and rebaixamento.motivo == "valor_sem_lastro":
        return montar_generico("elem.1", trecho), rebaixamento
    return convertido, rebaixamento


def _aplicar(
    operacao: dict[str, Any],
    nucleo: dict[str, ValorRegra],
    parametros: dict[str, ValorRegra],
    elementos: list[_Elemento],
    texto: str,
    publicadas: Sequence[str],
) -> MotivoDiagnostico | None:
    tipo = operacao["tipo"]
    motivo: MotivoDiagnostico | None
    if tipo in ("definir_taxa_cargo", "remover_taxa_cargo"):
        atuais = cast(list[dict[str, ValorRegra]], nucleo.get("taxas_por_cargo", []))
        taxa_nova: dict[str, ValorRegra] | None = None
        if tipo == "definir_taxa_cargo":
            taxa_nova, motivo = conferir_taxa_por_cargo(operacao["valor"], texto)
            if taxa_nova is None:
                return motivo
            cargo = taxa_nova["cargo"]
        else:
            campo = operacao["cargo"]
            cargo, motivo = resolver_codigo("cargo", campo["valor"], campo["trecho"], texto)
            if cargo is None:
                return motivo
            if not any(taxa["cargo"] == cargo for taxa in atuais):
                return "referencia_inexistente"
        novas: list[ValorRegra] = []
        inserida = False
        for taxa in atuais:
            if taxa["cargo"] != cargo:
                novas.append(taxa)
            elif taxa_nova is not None and not inserida:
                novas.append(taxa_nova)
                inserida = True
        if taxa_nova is not None and not inserida:
            novas.append(taxa_nova)
        if novas:
            nucleo["taxas_por_cargo"] = novas
        else:
            nucleo.pop("taxas_por_cargo", None)
        escopo = nucleo.get("cargo")
        destinatarios = [taxa["cargo"] for taxa in atuais]
        if (
            novas
            and "percentual" not in nucleo
            and (
                escopo is None
                or (isinstance(escopo, list) and escopo and set(escopo) == set(destinatarios))
            )
        ):
            nucleo["cargo"] = list(
                dict.fromkeys(
                    cast(str, taxa["cargo"]) for taxa in cast(list[dict[str, ValorRegra]], novas)
                )
            )
    elif tipo in ("definir_nucleo", "definir_parametro"):
        campo = operacao["campo"]
        conferido, motivo = _conferir(
            campo, operacao["valor"], texto, publicadas, operacao["trecho"]
        )
        if motivo is not None:
            return motivo
        valor = _VALOR.validate_python(conferido, strict=True)
        if tipo == "definir_nucleo":
            candidato = {**nucleo, campo: valor}
            RepresentacaoRegra.model_validate({"nucleo": candidato, "especificacoes": []})
            nucleo[campo] = valor
        else:
            validar_parametros({**parametros, campo: valor})
            parametros[campo] = valor
    elif tipo == "remover_parametro":
        parametros.pop(operacao["campo"], None)
    elif tipo == "adicionar_elemento":
        convertido, rebaixamento = _montar_elemento_correcao(
            operacao["elemento"], operacao["trecho"], texto, publicadas
        )
        elementos.append(_Elemento(None, convertido, rebaixamento))
    else:
        posicao = next(
            (i for i, e in enumerate(elementos) if e.ref_original == operacao["ref"]), None
        )
        if posicao is None:
            return "referencia_inexistente"
        if tipo == "remover_elemento":
            elementos.pop(posicao)
        else:
            convertido, rebaixamento = _montar_elemento_correcao(
                operacao["elemento"],
                operacao["trecho"],
                texto,
                publicadas,
                elemento_atual=elementos[posicao].conteudo,
            )
            # O trecho isolado da correção não preserva as condições do elemento original.
            if rebaixamento is not None and rebaixamento.motivo == "valor_sem_lastro":
                return "valor_sem_lastro"
            elementos[posicao] = _Elemento(operacao["ref"], convertido, rebaixamento)
    return None


def aplicar_operacoes_correcao(
    representacao: RepresentacaoRegra,
    parametros: dict[str, ValorRegra],
    operacoes: object,
    competencias_publicadas: Sequence[str],
    *,
    texto_correcao: str,
) -> ResultadoCorrecao:
    """Aplica um envelope desserializado; interface e diagnósticos em docs/correcao.md.

    As competências publicadas só resolvem o ano que o trecho não diz, como na extração
    inicial: um período fora delas é aceito, para a validação de domínio apontá-lo (T-277).
    """
    if not Draft202012Validator(schema_envelope_correcao()).is_valid(operacoes):
        raise FalhaExtracaoError("Envelope de correção inválido")

    regra = deepcopy(representacao.para_contrato())
    nucleo = cast(dict[str, ValorRegra], regra["nucleo"])
    especificacoes = cast(list[dict[str, ValorRegra]], regra["especificacoes"])
    elementos = [_Elemento(cast(str, e["ref"]), e) for e in especificacoes]
    refs = [e.ref_original for e in elementos]
    if len(refs) != len(set(refs)):
        raise FalhaExtracaoError("Referências da regra atual ambíguas")
    completos = deepcopy(validar_parametros(parametros))
    envelope = cast(dict[str, Any], operacoes)
    diagnosticos: list[DiagnosticoCorrecao] = []
    # A montagem da T-203 recupera rascunhos incompletos; o envelope do item segue fechado.
    validador = Draft202012Validator(schema_operacao_correcao(validar_elemento=False))
    for indice, operacao in enumerate(envelope["operacoes"], 1):
        if isinstance(operacao, dict) and not trecho_literal(
            texto_correcao, operacao.get("trecho")
        ):
            diagnosticos.append(DiagnosticoOperacao(indice, "operacao_sem_trecho"))
            continue
        if not validador.is_valid(operacao):
            diagnosticos.append(DiagnosticoOperacao(indice, "operacao_invalida"))
            continue
        motivo: MotivoDiagnostico | None = "operacao_invalida"
        with suppress(ValueError, TypeError, KeyError, RecursionError):
            motivo = _aplicar(
                deepcopy(operacao),
                nucleo,
                completos,
                elementos,
                texto_correcao,
                competencias_publicadas,
            )
        if motivo is not None:
            diagnosticos.append(DiagnosticoOperacao(indice, motivo))

    finais: list[ValorRegra] = []
    for indice, elemento in enumerate(elementos, 1):
        ref = f"elem.{indice}"
        finais.append({**elemento.conteudo, "ref": ref})
        if elemento.rebaixamento is not None:
            diagnosticos.append(replace(elemento.rebaixamento, ref=ref))
    regra["especificacoes"] = finais
    return RepresentacaoRegra.model_validate(regra), validar_parametros(completos), diagnosticos
