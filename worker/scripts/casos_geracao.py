"""Casos de geração (T-243): o formato, a execução no sandbox e a comparação com o esperado.

Um caso é uma regra (a representação), o período, uma implementação de referência escrita à
mão e o resultado que ela produz no sandbox. Cada caso é uma pasta em
``tests/fixtures/casos_geracao/<id>/`` com três arquivos:

- ``caso.json``: ``id``, ``descricao`` (o que o caso prova), ``leitura`` (a interpretação da
  regra que a referência implementa), ``representacao`` e ``competencias``;
- ``referencia.py``: a implementação de referência, contra o contrato ``RegraFn``;
- ``esperado.json``: o que a referência produz no sandbox, gravado por
  ``scripts.gravar_esperado`` e nunca escrito à mão.

O código, de referência ou gerado, só roda no container, pelo mesmo caminho da fila:
``executar_no_sandbox``, ``classificar`` e ``julgar``, com os elementos que a regra do caso exige,
para a conferência de cobertura (T-241) valer também aqui. Nada aqui o importa no processo do
worker. Do que volta do container só se guarda a classe, o motivo, os totais, a quebra por
elemento e os elementos que reprovaram a cobertura: nunca linha de dataset, stdout, stderr ou
mensagem de erro.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from app.execucao.baseline import carregar_baselines, localizar
from app.execucao.coleta import Classe, Motivo, classificar
from app.execucao.container import executar_no_sandbox
from app.execucao.preparo import PayloadContainer
from app.execucao.schema import validador
from app.execucao.veredito import Julgamento, julgar
from app.sandbox.carga import competencias_publicadas
from app.sandbox.resultado import Totais

WORKER_ROOT = Path(__file__).resolve().parents[1]
DIRETORIO_CASOS = WORKER_ROOT / "tests" / "fixtures" / "casos_geracao"
ARQUIVO_CASO = "caso.json"
ARQUIVO_REFERENCIA = "referencia.py"
ARQUIVO_ESPERADO = "esperado.json"
ESQUEMA_REPRESENTACAO = "representacao-regra.schema.json"

# A tolerância do harness é de um centavo por linha (matrícula e competência), ao conferir a
# atribuição (app/sandbox/resultado.py). A comissão de cada linha é arredondada a centavos, e duas
# fórmulas equivalentes (`venda * 0.025` e `venda / 40`) podem arredondar um meio centavo para
# lados opostos. Comparando agregados, a mesma tolerância vale um centavo por linha do período.
CENTAVO = Decimal("0.01")

# O veredito não interessa ao avaliador, mas `classificar` e `julgar` pedem um orçamento: ele
# só decide viável ou inviável, que nunca é lido aqui.
ORCAMENTO_SEM_VEREDITO = 0.0

CAMPOS_CASO = frozenset({"id", "descricao", "leitura", "representacao", "competencias"})
CAMPOS_ESPERADO_SUCESSO = frozenset({"competencias", "classe", "motivo", "totais", "elemento"})
CAMPOS_ESPERADO_FALHA = frozenset({"competencias", "classe", "motivo", "tipo_erro"})

type DesfechoAvaliacao = Literal["bate", "diverge", "falhou_como_esperado", "falhou_sem_esperar"]
DESFECHOS_APROVADOS: frozenset[DesfechoAvaliacao] = frozenset({"bate", "falhou_como_esperado"})


class CasoInvalidoError(ValueError):
    """Um caso fora do formato: arquivo ausente, campo faltando ou representação inválida."""


@dataclass(frozen=True)
class Caso:
    id: str
    descricao: str
    leitura: str
    representacao: Mapping[str, Any]
    competencias: tuple[str, ...]
    diretorio: Path

    @property
    def referencia(self) -> Path:
        return self.diretorio / ARQUIVO_REFERENCIA

    @property
    def esperado(self) -> Path:
        return self.diretorio / ARQUIVO_ESPERADO

    @property
    def elementos_exigidos(self) -> list[str]:
        """Os elementos que o comando executar-codigo exigiria para esta regra (T-240), montados
        como o codegen os monta (T-242): ``nucleo.percentual`` quando o núcleo tem percentual, e
        o ``ref`` de cada especificação, na ordem."""
        exigidos = ["nucleo.percentual"] if "percentual" in self.representacao["nucleo"] else []
        exigidos.extend(elemento["ref"] for elemento in self.representacao["especificacoes"])
        return exigidos


@dataclass(frozen=True)
class Medicao:
    """O que se lê de uma execução para compará-la.

    Em sucesso, os totais e a quebra por elemento; em falha, a classe, o motivo, numa
    exceção da regra o nome do tipo dela, e numa cobertura incompleta os elementos que a
    reprovaram. O tipo vindo de código gerado só é comparado, nunca exibido.
    """

    classe: Classe
    motivo: Motivo
    totais: Totais | None = None
    elemento: Mapping[str, float] | None = None
    tipo_erro: str | None = None
    elementos_ausentes: tuple[str, ...] = ()
    elementos_fora_da_regra: tuple[str, ...] = ()


# A única falha que um caso pode esperar: a regra levanta NotImplementedError, como o contrato
# do harness manda para o elemento que os dados não permitem calcular. Exigir o tipo impede que
# um KeyError, um timeout ou uma saída fora do contrato passem por recusa deliberada.
FALHA_ESPERADA = Medicao("erro_codigo", "excecao", tipo_erro="NotImplementedError")


@dataclass(frozen=True)
class DiferencaElemento:
    elemento: str
    esperado: float
    obtido: float


@dataclass(frozen=True)
class Avaliacao:
    caso: str
    desfecho: DesfechoAvaliacao
    esperado: Medicao
    obtido: Medicao
    tolerancia: Decimal
    diferencas: tuple[DiferencaElemento, ...] = ()

    @property
    def passou(self) -> bool:
        return self.desfecho in DESFECHOS_APROVADOS


# ---- o formato ----


def carregar_casos(
    ids: Sequence[str] | None = None, *, diretorio: Path = DIRETORIO_CASOS
) -> list[Caso]:
    """Os casos da pasta, em ordem de id, ou só os pedidos, na ordem pedida."""
    if ids:
        return [carregar_caso(diretorio / caso_id) for caso_id in ids]
    pastas = sorted(pasta for pasta in diretorio.iterdir() if pasta.is_dir())
    if not pastas:
        raise CasoInvalidoError(f"nenhum caso em {diretorio}")
    return [carregar_caso(pasta) for pasta in pastas]


def carregar_caso(diretorio: Path) -> Caso:
    arquivo = diretorio / ARQUIVO_CASO
    if not arquivo.is_file():
        raise CasoInvalidoError(f"{diretorio.name}: {ARQUIVO_CASO} não encontrado")
    if not (diretorio / ARQUIVO_REFERENCIA).is_file():
        raise CasoInvalidoError(f"{diretorio.name}: {ARQUIVO_REFERENCIA} não encontrado")
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    if not isinstance(dados, dict) or set(dados) != CAMPOS_CASO:
        raise CasoInvalidoError(
            f"{diretorio.name}: {ARQUIVO_CASO} precisa ter exatamente {sorted(CAMPOS_CASO)}"
        )
    if dados["id"] != diretorio.name:
        raise CasoInvalidoError(f"{diretorio.name}: o id do caso é {dados['id']!r}")
    for campo in ("descricao", "leitura"):
        if not isinstance(dados[campo], str) or not dados[campo].strip():
            raise CasoInvalidoError(f"{diretorio.name}: {campo} precisa ser texto não vazio")
    _conferir_representacao(diretorio.name, dados["representacao"])
    return Caso(
        id=dados["id"],
        descricao=dados["descricao"],
        leitura=dados["leitura"],
        representacao=dados["representacao"],
        competencias=_conferir_competencias(diretorio.name, dados["competencias"]),
        diretorio=diretorio,
    )


def _conferir_representacao(caso_id: str, representacao: object) -> None:
    erros = list(validador(ESQUEMA_REPRESENTACAO).iter_errors(representacao))
    if erros:
        caminhos = sorted("$" + "".join(f"/{p}" for p in erro.absolute_path) for erro in erros)
        raise CasoInvalidoError(f"{caso_id}: a representação não valida no schema: {caminhos}")


def _conferir_competencias(caso_id: str, competencias: object) -> tuple[str, ...]:
    """O período chega ao harness como o comando o mandaria: não vazio, sem repetição, em
    ordem crescente e só com competências que o dataset publica."""
    if (
        not isinstance(competencias, list)
        or not competencias
        or not all(isinstance(c, str) for c in competencias)
    ):
        raise CasoInvalidoError(f"{caso_id}: competencias precisa ser uma lista de AAAA-MM")
    periodo = tuple(cast(list[str], competencias))
    if list(periodo) != sorted(set(periodo)):
        raise CasoInvalidoError(f"{caso_id}: competencias precisa ser crescente e sem repetição")
    publicadas = competencias_publicadas()
    fora = [c for c in periodo if c not in publicadas]
    if fora:
        raise CasoInvalidoError(f"{caso_id}: competências fora do dataset: {fora}")
    return periodo


# ---- o esperado em disco ----


def serializar_esperado(caso: Caso, medicao: Medicao) -> str:
    """Determinístico: o mesmo resultado produz os mesmos bytes, o que permite o --check."""
    dados: dict[str, object] = {
        "competencias": list(caso.competencias),
        "classe": medicao.classe,
        "motivo": medicao.motivo,
    }
    if medicao.totais is not None:
        dados["totais"] = dict(medicao.totais)
    if medicao.elemento is not None:
        dados["elemento"] = dict(medicao.elemento)
    if medicao.tipo_erro is not None:
        dados["tipo_erro"] = medicao.tipo_erro
    return json.dumps(dados, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def ler_esperado(caso: Caso) -> Medicao:
    if not caso.esperado.is_file():
        raise CasoInvalidoError(
            f"{caso.id}: {ARQUIVO_ESPERADO} não encontrado; grave-o com scripts.gravar_esperado"
        )
    dados = json.loads(caso.esperado.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise CasoInvalidoError(f"{caso.id}: {ARQUIVO_ESPERADO} precisa ser um objeto")
    if dados.get("competencias") != list(caso.competencias):
        raise CasoInvalidoError(
            f"{caso.id}: {ARQUIVO_ESPERADO} foi gravado para outro período; grave-o de novo"
        )
    if dados.get("classe") == "sucesso":
        if set(dados) != CAMPOS_ESPERADO_SUCESSO or dados["motivo"] != "ok":
            raise CasoInvalidoError(f"{caso.id}: {ARQUIVO_ESPERADO} de sucesso fora do formato")
        totais = dados["totais"]
        return Medicao(
            "sucesso",
            "ok",
            totais=Totais(
                baseline=totais["baseline"],
                simulado=totais["simulado"],
                diferenca_abs=totais["diferenca_abs"],
                diferenca_pct=totais["diferenca_pct"],
            ),
            elemento=dict(dados["elemento"]),
        )
    if set(dados) != CAMPOS_ESPERADO_FALHA:
        raise CasoInvalidoError(f"{caso.id}: {ARQUIVO_ESPERADO} de falha fora do formato")
    falha = Medicao(
        cast(Classe, dados["classe"]),
        cast(Motivo, dados["motivo"]),
        tipo_erro=dados["tipo_erro"],
    )
    if falha != FALHA_ESPERADA:
        raise CasoInvalidoError(
            f"{caso.id}: {ARQUIVO_ESPERADO} registra uma falha diferente da esperada"
        )
    return falha


# ---- a execução ----


def executar_caso(caso: Caso, fonte: str, *, imagem: str | None = None) -> Medicao:
    """Roda ``fonte`` no sandbox com o período do caso e mede o desfecho.

    A sequência é a do consumidor: o mesmo isolamento, a mesma classificação, a mesma
    conferência do baseline congelado, que reprova um código que adultera o baseline, e a mesma
    conferência de cobertura, com os elementos que a regra do caso exige.
    """
    payload = PayloadContainer(
        job_id=uuid4(),
        codigo_gerado_id=uuid4(),
        linguagem="python",
        fonte=fonte,
        competencias=list(caso.competencias),
    )
    saida = executar_no_sandbox(payload, imagem=imagem)
    desfecho = classificar(saida, payload, ORCAMENTO_SEM_VEREDITO)
    julgamento = julgar(
        desfecho,
        list(caso.competencias),
        ORCAMENTO_SEM_VEREDITO,
        carregar_baselines(),
        elementos_exigidos=caso.elementos_exigidos,
    )
    return medir(julgamento)


def medir(julgamento: Julgamento) -> Medicao:
    if julgamento.classe == "sucesso" and julgamento.resultado is not None:
        totais = julgamento.resultado["totais"]
        return Medicao(
            "sucesso",
            "ok",
            totais=Totais(
                baseline=totais["baseline"],
                simulado=totais["simulado"],
                diferenca_abs=totais["diferenca_abs"],
                diferenca_pct=totais["diferenca_pct"],
            ),
            elemento=dict(julgamento.resultado["decomposicao"]["elemento"]),
        )
    desfecho = julgamento.desfecho
    tipo_erro = None
    if julgamento.motivo == "excecao" and desfecho is not None and desfecho.erro is not None:
        tipo_erro = desfecho.erro["tipo"]
    cobertura = julgamento.cobertura
    return Medicao(
        julgamento.classe,
        julgamento.motivo,
        tipo_erro=tipo_erro,
        elementos_ausentes=cobertura.ausentes if cobertura is not None else (),
        elementos_fora_da_regra=cobertura.fora_da_regra if cobertura is not None else (),
    )


# ---- a comparação ----


def tolerancia_do_periodo(competencias: Sequence[str]) -> Decimal:
    """Um centavo por linha do baseline congelado do período, contadas no manifesto."""
    manifesto = json.loads((localizar() / "manifesto.json").read_text(encoding="utf-8"))
    linhas = sum(int(manifesto["baselines"][c]["matriculas"]) for c in competencias)
    return CENTAVO * linhas


def comparar(caso_id: str, esperado: Medicao, obtido: Medicao, tolerancia: Decimal) -> Avaliacao:
    """Um dos quatro desfechos.

    Num caso que espera falha, devolver um número é ``diverge``: a regra foi simulada pela
    metade. Falhar de outro jeito, como um ``KeyError`` ou um timeout, é ``falhou_sem_esperar``.
    """
    if esperado.classe != "sucesso":
        if _mesma_falha(esperado, obtido):
            return Avaliacao(caso_id, "falhou_como_esperado", esperado, obtido, tolerancia)
        if obtido.classe == "sucesso":
            return Avaliacao(caso_id, "diverge", esperado, obtido, tolerancia)
        return Avaliacao(caso_id, "falhou_sem_esperar", esperado, obtido, tolerancia)

    if obtido.classe != "sucesso":
        return Avaliacao(caso_id, "falhou_sem_esperar", esperado, obtido, tolerancia)

    assert esperado.totais is not None and obtido.totais is not None
    diferencas = diferencas_por_elemento(esperado.elemento or {}, obtido.elemento or {}, tolerancia)
    total_bate = dentro_da_tolerancia(
        esperado.totais["simulado"], obtido.totais["simulado"], tolerancia
    )
    desfecho: DesfechoAvaliacao = "bate" if total_bate and not diferencas else "diverge"
    return Avaliacao(caso_id, desfecho, esperado, obtido, tolerancia, diferencas)


def diferencas_por_elemento(
    esperado: Mapping[str, float], obtido: Mapping[str, float], tolerancia: Decimal
) -> tuple[DiferencaElemento, ...]:
    """A decomposição só tem chave para elemento com contribuição: chave ausente vale zero."""
    return tuple(
        DiferencaElemento(elemento, esperado.get(elemento, 0.0), obtido.get(elemento, 0.0))
        for elemento in sorted(esperado.keys() | obtido.keys())
        if not dentro_da_tolerancia(
            esperado.get(elemento, 0.0), obtido.get(elemento, 0.0), tolerancia
        )
    )


def dentro_da_tolerancia(esperado: float, obtido: float, tolerancia: Decimal) -> bool:
    return abs(Decimal(str(esperado)) - Decimal(str(obtido))) <= tolerancia


def _mesma_falha(esperado: Medicao, obtido: Medicao) -> bool:
    return (esperado.classe, esperado.motivo, esperado.tipo_erro) == (
        obtido.classe,
        obtido.motivo,
        obtido.tipo_erro,
    )
