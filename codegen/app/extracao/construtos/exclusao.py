import re
from typing import Any, cast

from app.extracao.construto import Construto, ContextoExtracao, com_lastro
from app.extracao.lastro import normalizar
from app.extracao.modelos import ElementoRebaixadoError
from app.extracao.vocabulario import CampoCodigo, FalhaCodigo, resolver_codigo
from app.tipos_estado import ValorRegra

# A exclusão inteira depende de cada código ter lastro próprio; um código desconhecido não
# pode ser substituído por outro que apareça na mesma evidência.
_CODIGOS = {"type": "array", "minItems": 1, "items": com_lastro({"type": "string", "minLength": 1})}

# A dimensão não admite matrícula, e o número de uma matrícula pode coincidir com o código de uma
# loja: o trecho que fala de matrícula não chega à resolução de códigos.
_MATRICULA = re.compile(r"\bmatric(?:ulas?)?\b")
# Uma exceção que vem junto de um valor próprio restringe esse efeito, não a regra inteira, e o
# contrato só representa a exclusão da regra inteira.
_EFEITO_PROPRIO = re.compile(r"%|R\$")
_EFEITO_POR_EXTENSO = re.compile(r"\b(?:por cento|reais)\b")
_NOME_EFEITO = r"(?:bonus|premios?|adiciona(?:l|is)|acrescimos?|faixas?)"
_EFEITO_RESTRITO = re.compile(rf"\b{_NOME_EFEITO}\b")
_ALCANCE_GLOBAL = re.compile(
    r"^(?:(?:e|mas) )?(?:(?:a|esta|essa) regra(?: inteira| toda| como um todo)?|"
    r"toda a regra|todos os efeitos(?: da regra)?)"
    rf"(?: inclusive (?:(?:o|a|os|as) )?{_NOME_EFEITO})?"
    r" (?:nao (?:se )?(?:aplica|aplicam|vale|valem)|exclui|excluem|exceto|salvo|com excecao)\b"
)
_RETOMA_ANTERIOR = re.compile(
    r"^(?:(?:e|mas) )?(?:(?:ele|ela|eles|elas|isso|isto|esse beneficio|este beneficio|"
    r"essa vantagem|esta vantagem)\b|(?:nao|nunca) (?:se )?(?:aplica|aplicam|vale|valem)\b|"
    r"(?:exceto|salvo|menos)\b)"
)
# Pontos dentro de números não encerram a frase que vincula a exceção ao efeito.
_FIM_FRASE = re.compile(r"(?<!\d)\.|\.(?!\d)|[!?;]")


def _alcance_global_explicito(frase: str) -> bool:
    afirmacao = _ALCANCE_GLOBAL.match(frase)
    return afirmacao is not None and _EFEITO_RESTRITO.search(frase[afirmacao.end() :]) is None


def _excecao_de_efeito(trecho: str, texto: str) -> bool:
    frase = normalizar(trecho)
    if _alcance_global_explicito(frase):
        return False
    if (
        _EFEITO_PROPRIO.search(trecho)
        or _EFEITO_POR_EXTENSO.search(frase)
        or _EFEITO_RESTRITO.search(frase)
    ):
        return True
    limites = [0, *(fim.end() for fim in _FIM_FRASE.finditer(texto)), len(texto)]
    for ocorrencia in re.finditer(re.escape(trecho), texto):
        inicio = max(limite for limite in limites if limite <= ocorrencia.start())
        fim = next(limite for limite in limites if limite >= ocorrencia.end())
        atual = normalizar(texto[inicio:fim])
        if _alcance_global_explicito(atual):
            continue
        if _EFEITO_RESTRITO.search(atual):
            return True
        inicio_anterior = max((limite for limite in limites if limite < inicio), default=0)
        anterior = normalizar(texto[inicio_anterior:inicio])
        if _RETOMA_ANTERIOR.match(atual) and _EFEITO_RESTRITO.search(anterior):
            return True
    return False


def converter(rascunho: dict[str, Any], contexto: ContextoExtracao) -> dict[str, ValorRegra]:
    trecho: str = rascunho["trecho"]
    frase = normalizar(trecho)
    if _MATRICULA.search(frase):
        raise ValueError("Exclusão de matrícula")
    if _excecao_de_efeito(trecho, contexto.texto):
        raise ElementoRebaixadoError("termo_ambiguo")

    dimensao = cast(CampoCodigo, rascunho["dimensao"])
    resolvidos: list[ValorRegra] = []
    falha: FalhaCodigo | None = None
    for campo in rascunho["valores"]:
        codigo, motivo = resolver_codigo(
            dimensao,
            campo["valor"],
            campo["trecho"],
            trecho,
            exigir_termo_conhecido=True,
        )
        if codigo is None:
            falha = falha or motivo
        elif codigo not in resolvidos:
            resolvidos.append(codigo)
    if falha is not None:
        # Excluir só os códigos resolvidos mudaria o resultado sem aviso; eles seguem no genérico
        # para a confirmação.
        campos: dict[str, ValorRegra] = {"dimensao": dimensao}
        if resolvidos:
            campos["valores"] = resolvidos
        raise ElementoRebaixadoError(falha, campos)
    return {"dimensao": dimensao, "valores": resolvidos}


EXCLUSAO = Construto(
    # Sem as descrições, a variante exclusao no anyOf levava o modelo a devolver como generico
    # condições por limiar sem exceção nenhuma. Elas não citam as palavras da exceção entre
    # aspas: o modelo passou a copiá-las em minúsculas no trecho, que deixava de ser literal.
    propriedades={
        "dimensao": {
            "type": "string",
            "enum": ["loja", "marca", "cargo"],
            "description": (
                "Dimensão de onde uma exceção explícita retira códigos da regra inteira. "
                "Condição sobre a venda (até, menor que, acima de, no mínimo) não é exclusao: "
                "é condicao_limiar."
            ),
        },
        "valores": {
            **_CODIGOS,
            "description": "Códigos que a exceção retira, um {valor, trecho} por código.",
        },
    },
    obrigatorios=("dimensao", "valores"),
    instrucoes=(
        "exclusao: retira da regra inteira os códigos listados de uma dimensão (loja, marca ou "
        "cargo). Um elemento por dimensão: excluir um cargo e uma marca são dois elementos, na "
        "ordem do texto. valores é uma lista de {valor, trecho}, um por código, como "
        "loja/marca/cargo do núcleo: valor é o código ou o nome como o texto o diz ('150', "
        "'gerente', '13'), mesmo fora do vocabulário, porque o motor confere e rebaixa; trecho é "
        "a parte literal do texto que cita só aquele código. O trecho do elemento é só a frase "
        "da exceção, e a descricao não acrescenta código que o trecho não diz. O núcleo traz o "
        "que o texto inclui e a exclusao o que o texto exclui, cada um como foi dito. 'Todas as "
        "lojas, menos a 13' só exclui: loja fica ausente do núcleo. 'Somente a loja 13' só "
        "inclui: é núcleo, não exclusao. Um código que o texto inclui fica no núcleo mesmo "
        "quando também é excluído; a contradição é apontada depois, nunca corrigida aqui. "
        "Exemplos: 'Válido para todas as marcas e para todos os cargos, com exceção dos gerentes "
        "(150)' -> exclusao de cargo, valores [{valor:'150', trecho:'gerentes (150)'}], sem "
        "marca nem cargo no núcleo; 'Esta regra não se aplica aos cargos de gerente' -> exclusao "
        "de cargo, valores [{valor:'gerente', trecho:'gerente'}]; 'Para todas as lojas, exceto a "
        "13 e a 58' -> exclusao de loja, valores [{valor:'13', trecho:'13'}, {valor:'58', "
        "trecho:'58'}]; 'Pague 2% nas lojas 13 e 58, exceto a loja 13' -> nucleo.loja com 13 e "
        "58, e exclusao de loja com valores [{valor:'13', trecho:'loja 13'}]; 'Comissão de 1%. "
        "Não vale para a loja 5.' -> exclusao de loja com trecho 'Não vale para a loja 5', com o "
        "N maiúsculo como no texto, e valores [{valor:'5', trecho:'loja 5'}]. É generico, com a "
        "frase literal inteira: exceção de matrícula ('exceto a matrícula MATRIC-422'); exceção "
        "que vale só para um efeito (um bônus em reais, um acréscimo, uma faixa) ou só para uma "
        "de várias regras do texto, mantida junto desse efeito ou regra em um único generico. "
        "'Este bônus não se aplica aos cargos de gerente' é generico mesmo sem repetir o valor "
        "do bônus. Não recorte só a exceção de uma frase que também define o efeito: "
        "'Bônus de R$ 500 para todos, exceto os gerentes' fica inteiro em um generico. "
        "O sujeito da exclusão define seu alcance: 'A regra inteira, inclusive o bônus, não se "
        "aplica aos gerentes (150)' é exclusao de cargo 150, mesmo que outra cláusula fale de "
        "bônus. Já 'Bônus de R$ 500 para a matrícula 422. Ele não se aplica aos gerentes' "
        "restringe só o bônus: preserve o bônus e sua exceção juntos em um único generico, "
        "mesmo separados por ponto ou ponto e vírgula; não extraia bônus e exclusão separados. "
        "Quando o texto tem várias regras, o núcleo é só a primeira; as outras, com seus "
        "códigos, percentuais e exceções, ficam em um único generico e nunca entram no núcleo: "
        "'Comissão de 1% na loja 5. Na loja 7, comissão de 4%, menos para o cargo 300' -> nucleo "
        "com 1% e loja 5, e um generico com 'Na loja 7, comissão de 4%, menos para o cargo 300'; "
        "loja 7 e 4% não entram no núcleo."
    ),
    converter=converter,
)
