"""Coleta e classificação do desfecho de uma execução (T-065).

``executar_no_sandbox`` (T-064) devolve fatos: código de saída, ``OOMKilled``, prazo estourado
e os bytes de stdout e stderr. Aqui esses fatos viram uma **classe**, no vocabulário de
``resultados_simulacao.status`` e de ``simulacao-concluida``:

- ``sucesso``: o envelope diz sucesso e o resultado valida contra o schema da T-034;
- ``assercao_violada``: o código rodou e produziu números, mas uma invariante foi violada e o
  número não vale;
- ``erro_codigo``: a regra falhou, estourou prazo ou memória, ou não devolveu uma saída que se
  sustente. Repetir o mesmo código daria o mesmo resultado, então quem trata é a regeneração;
- ``erro_infra``: o container não pôde ser criado, iniciado ou lido. É o único desfecho que
  justifica repetir o comando sem gerar código de novo.

Tudo que vem do container é dado não confiável, inclusive o envelope inteiro: a regra divide
o processo com o harness e pode forjar qualquer byte do stdout. Por isso a classificação
confere forma, identidade e coerência, e na dúvida culpa o código, nunca a infraestrutura.
Nenhum número é interpretado nem recalculado; o resultado segue como veio (T-066 o julga).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from app.core.logger import get_logger
from app.core.metrics.global_metrics import sandbox_envelope_bytes
from app.execucao.container import SaidaBruta
from app.execucao.preparo import PayloadContainer
from app.execucao.schema import Problema, validar_assercoes, validar_linhas, validar_resultado
from app.sandbox.assercoes import Desfecho
from app.sandbox.envelope import SAIDA_POR_STATUS, VERSAO, Envelope, Falha
from app.sandbox.resultado import PADRAO_ELEMENTO_REF, LinhasResultado, ResultadoSimulacao

logger = get_logger("app.execucao.coleta")

type Classe = Literal["sucesso", "assercao_violada", "erro_codigo", "erro_infra"]

# Por que a classe saiu como saiu. Serve a log, métricas e à gravação (T-067); nunca carrega
# conteúdo vindo do container.
type Motivo = Literal[
    "ok",
    "assercao",
    "excecao",
    "timeout",
    "memoria",
    "saida_truncada",
    "sem_envelope",
    "envelope_invalido",
    "envelope_de_outra_execucao",
    "codigo_de_saida_divergente",
    "resultado_fora_do_schema",
    # Atribuído no julgamento (T-066): o total do baseline que saiu do container não é o que o
    # worker tem congelado, ou os totais não fecham entre si.
    "baseline_divergente",
    # Atribuído no julgamento (T-241): o comando exigiu um elemento que o código não declarou,
    # ou o código atribuiu contribuição a um elemento que o comando não exige.
    "cobertura_incompleta",
    "infra",
]


@dataclass(frozen=True)
class DesfechoClassificado:
    """A classe e o que a sustenta. ``resultado``, ``erro`` e ``saida`` são conteúdo do
    container: ficam fora do ``repr`` para não chegarem a um log por descuido."""

    classe: Classe
    motivo: Motivo
    assercoes: list[Desfecho] = field(default_factory=list, repr=False)
    # Só em sucesso, e é o objeto do envelope como veio: sem orçamento, sem recomposição.
    resultado: ResultadoSimulacao | None = field(default=None, repr=False)
    linhas: LinhasResultado | None = field(default=None, repr=False)
    # Só em sucesso: os elementos que o código gerado declarou implementar, cada um no espaço de
    # elemento_ref. None quando ele não declarou nada; quem julga isso é a T-241, no veredito.
    elementos_implementados: tuple[str, ...] | None = field(default=None, repr=False)
    # Só em erro_codigo com envelope: tipo, mensagem e quadros da regra. Texto para o
    # usuário, nunca instrução para um agente.
    erro: Falha | None = field(default=None, repr=False)
    # Onde o resultado falhou no schema: caminho e palavra-chave, sem valores.
    problemas: tuple[Problema, ...] = ()
    # O que o container escreveu, capturado em toda execução. None em erro_infra, em que
    # nada rodou.
    saida: SaidaBruta | None = field(default=None, repr=False)


def classificar_falha_de_infra() -> DesfechoClassificado:
    return DesfechoClassificado(classe="erro_infra", motivo="infra")


def classificar(
    saida: SaidaBruta, payload: PayloadContainer, orcamento: float | None
) -> DesfechoClassificado:
    """Decide a classe de uma execução que chegou ao fim. A primeira regra que casa vence."""
    if saida.estourou_timeout:
        return _erro_codigo("timeout", saida)
    if saida.oom_killed:
        return _erro_codigo("memoria", saida)
    if saida.stdout_truncado:
        return _erro_codigo("saida_truncada", saida)
    if not saida.stdout:
        return _erro_codigo("sem_envelope", saida)

    dados = _ler_envelope(saida.stdout)
    if dados is None or not _forma_valida(dados):
        return _erro_codigo("envelope_invalido", saida)
    envelope = cast(Envelope, dados)

    if (
        envelope["job_id"] != str(payload.job_id)
        or envelope["codigo_gerado_id"] != str(payload.codigo_gerado_id)
        or envelope["competencias"] != list(payload.competencias)
    ):
        return _erro_codigo("envelope_de_outra_execucao", saida)
    if saida.codigo_saida != SAIDA_POR_STATUS[envelope["status"]]:
        return _erro_codigo("codigo_de_saida_divergente", saida)

    sandbox_envelope_bytes.labels(status=envelope["status"]).observe(len(saida.stdout))

    assercoes = envelope["assercoes"]
    if envelope["status"] == "assercao_violada":
        return DesfechoClassificado("assercao_violada", "assercao", assercoes, saida=saida)
    if envelope["status"] == "erro_codigo":
        return DesfechoClassificado(
            "erro_codigo", "excecao", assercoes, erro=envelope["erro"], saida=saida
        )

    resultado = envelope["resultado"]
    assert resultado is not None  # garantido por _forma_valida para status "sucesso"
    problemas = validar_resultado(resultado, orcamento)
    linhas = envelope.get("linhas")
    problemas_linhas = validar_linhas(linhas, payload.competencias)
    if problemas_linhas:
        logger.info(
            "detalhamento recusado",
            extra={
                "status": "erro_codigo",
                "motivo": "resultado_fora_do_schema",
                "classes": [p["palavra_chave"] for p in problemas_linhas],
            },
        )
        problemas.extend(problemas_linhas)
    if problemas:
        return DesfechoClassificado(
            "erro_codigo",
            "resultado_fora_do_schema",
            assercoes,
            problemas=tuple(problemas),
            saida=saida,
        )
    elementos = envelope["elementos_implementados"]
    return DesfechoClassificado(
        "sucesso",
        "ok",
        assercoes,
        resultado=resultado,
        linhas=linhas,
        elementos_implementados=tuple(elementos) if elementos is not None else None,
        saida=saida,
    )


def _erro_codigo(motivo: Motivo, saida: SaidaBruta) -> DesfechoClassificado:
    return DesfechoClassificado("erro_codigo", motivo, saida=saida)


def _recusar_constante(constante: str) -> Any:
    raise ValueError(constante)


def _ler_envelope(stdout: bytes) -> dict[str, Any] | None:
    """O envelope é exatamente uma linha de JSON. Duas linhas, texto solto, ``NaN`` ou um JSON
    que não é objeto não são envelope."""
    try:
        texto = stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None
    texto = texto.removesuffix("\n")
    if not texto or "\n" in texto:
        return None
    try:
        dados = json.loads(texto, parse_constant=_recusar_constante)
    # 1 MiB de colchetes aninhados estoura a recursão do parser: código hostil, não bug nosso.
    except (ValueError, RecursionError):
        return None
    return dados if isinstance(dados, dict) else None


def _forma_valida(dados: Mapping[str, Any]) -> bool:
    """A forma e a coerência que o harness sempre produz. Um envelope que as contradiz não foi
    escrito por ele, ou foi escrito por uma regra que quis parecer sucesso."""
    # A ausência do detalhamento em sucesso pertence à validação do resultado, para
    # produzir resultado_fora_do_schema, não envelope_invalido.
    campos = set(dados)
    if dados.get("status") == "sucesso":
        campos.add("linhas")
    if campos != Envelope.__required_keys__:
        return False
    versao, status = dados["versao"], dados["status"]
    if type(versao) is not int or versao != VERSAO:
        return False
    if not isinstance(status, str) or status not in SAIDA_POR_STATUS:
        return False
    if not (isinstance(dados["job_id"], str) and isinstance(dados["codigo_gerado_id"], str)):
        return False
    competencias = dados["competencias"]
    if not (isinstance(competencias, list) and all(isinstance(c, str) for c in competencias)):
        return False
    assercoes = dados["assercoes"]
    if validar_assercoes(assercoes):
        return False
    violada = any(item["resultado"] == "violada" for item in assercoes)
    resultado, erro = dados["resultado"], dados["erro"]
    elementos = dados["elementos_implementados"]

    if status == "sucesso":
        # Uma violação num envelope de sucesso se contradiz: o número não valeria.
        return (
            isinstance(resultado, dict)
            and erro is None
            and not violada
            and resultado.get("assercoes") == assercoes
            and (elementos is None or _declaracao_valida(elementos))
        )
    # A declaração só acompanha um resultado: sem ele não há o que conferir.
    if elementos is not None or dados["linhas"] is not None:
        return False
    if status == "assercao_violada":
        return resultado is None and erro is None and violada
    return resultado is None and _falha_valida(erro)


def _declaracao_valida(elementos: object) -> bool:
    """A lista que o harness confere antes de escrever: identificadores de ``elemento_ref``. Só
    um identificador assim pode chegar ao diagnóstico ou ao log, nunca texto livre."""
    return isinstance(elementos, list) and all(
        isinstance(elemento, str) and PADRAO_ELEMENTO_REF.fullmatch(elemento)
        for elemento in elementos
    )


def _falha_valida(erro: object) -> bool:
    return (
        isinstance(erro, dict)
        and set(erro) == Falha.__required_keys__
        and all(isinstance(valor, str) for valor in erro.values())
    )
