"""As bases da apuração que o worker mantém por conta própria (T-270).

Com meta de venda, o container escala as vendas até a meta e reapura o baseline sobre elas
antes de chamar a regra (``app/sandbox/escalonamento.py``). Esse baseline não tem total
congelado com que ser conferido, e o que volta do container não se valida sozinho: a regra
divide o processo com o harness e alcança o baseline que ele guarda. O worker então faz a mesma
reapuração aqui, sobre a própria cópia das bases, e é esse total que confere o
``totais.baseline`` devolvido, como o congelado confere o de uma execução sem meta
(``app/execucao/baseline.py``).

Daqui também sai ``totais.vendas_historicas`` de toda execução com sucesso: o total de vendas
das competências, lido de uma fonte que o código gerado não alcança, como o orçamento. Da mesma
fonte sai o total vendido de cada linha do detalhamento (T-282).

Só stdlib: o motor de apuração (``app/sandbox/regras_competencia.py`` e o que ele importa) não
usa pandas, e o processo do worker não o carrega (``test_isolamento_harness.py``). Cada arquivo é
conferido contra o sha256 que o manifesto dos baselines registra em ``fontes_sha256``: são as
mesmas bases de que os baselines congelados e a imagem do sandbox saíram.

Da mesma conferência sai o registro das fontes de cada execução (T-311), gravado em
``resultados_simulacao.fontes``: a versão e o congelamento do manifesto, o sha256 de cada arquivo
de ``ARQUIVOS`` e o arquivo e o sha256 do baseline de cada competência. São referências; o
conteúdo das bases não entra no registro.
"""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import NoReturn, TypedDict

from app.execucao.baseline import (
    BaselineIndisponivelError,
    CompetenciaSemBaselineError,
    LinhasDoBaseline,
    indexar_linhas,
    localizar,
    total_das_linhas,
)
from app.sandbox.assercoes import AssercaoVioladaError
from app.sandbox.escalonamento import (
    MetaVendaError,
    escalar_vendas,
    fator_de_escala,
    reapurar_baseline,
    total_de_vendas,
)
from app.sandbox.regras_base import RegraBaseError

type Registro = Mapping[str, object]

# Os arquivos da reapuração, relativos à pasta das bases, que é também a chave de cada um em
# manifesto.json["fontes_sha256"].
ARQUIVOS = (
    "rh.jsonl",
    "vendas.jsonl",
    "comissoes.jsonl",
    "eventos_rh.jsonl",
    "regras_competencia.jsonl",
)

_SHA256 = re.compile(r"[0-9a-f]{64}")


class BasesIndisponiveisError(RuntimeError):
    """As bases não estão ao alcance do worker, ou não são as que o manifesto registra."""


class ReapuracaoNaMetaError(ValueError):
    """O baseline na meta não pôde ser reapurado: o comando pede uma competência sem bases, ou a
    meta não se aplica às vendas do período. Não é falha da regra, que nem chegou a rodar."""


class ManifestoDaExecucao(TypedDict):
    versao: int
    congelamento: str


class ArquivoDaExecucao(TypedDict):
    nome: str
    sha256: str


class BaselineDaExecucao(TypedDict):
    competencia: str
    arquivo: str
    sha256: str


class FontesDaExecucao(TypedDict):
    """``resultado-fontes.schema.json``: as bases que o worker conferiu, por referência."""

    manifesto: ManifestoDaExecucao
    competencias: list[str]
    arquivos: list[ArquivoDaExecucao]
    baselines: list[BaselineDaExecucao]


@dataclass(frozen=True)
class ManifestoDasBases:
    """O que o manifesto dos baselines registra das bases conferidas na subida."""

    versao: int
    # Data ISO, como o manifesto a registra.
    congelamento: str
    # Nome e sha256 de cada arquivo de ``ARQUIVOS``, na ordem de ``ARQUIVOS``. O sha256 é o que a
    # carga conferiu contra o conteúdo do arquivo.
    arquivos: tuple[tuple[str, str], ...]
    # Arquivo e sha256 do baseline de cada competência, como o manifesto os registra. Quem confere
    # o arquivo contra o sha256 é ``app/execucao/baseline.py``, que a subida também carrega.
    baselines: Mapping[str, tuple[str, str]]


@dataclass(frozen=True)
class BasesDoWorker:
    """As bases inteiras, como estão nos arquivos. Ninguém as altera: a reapuração trabalha
    sobre cópias."""

    # As competências com baseline congelado, as únicas que um comando pode pedir.
    competencias: frozenset[str]
    rh: tuple[Registro, ...]
    vendas: tuple[Registro, ...]
    comissoes: tuple[Registro, ...]
    eventos_rh: tuple[Registro, ...]
    regras: tuple[Registro, ...]
    manifesto: ManifestoDasBases = field(repr=False)

    def fontes(self, competencias: Sequence[str]) -> FontesDaExecucao:
        """O registro das fontes de uma execução nestas competências, na ordem do comando: o
        manifesto, os arquivos de base e o baseline de cada competência."""
        self._conferir(competencias)
        return FontesDaExecucao(
            manifesto=ManifestoDaExecucao(
                versao=self.manifesto.versao, congelamento=self.manifesto.congelamento
            ),
            competencias=list(competencias),
            arquivos=[
                ArquivoDaExecucao(nome=nome, sha256=sha256)
                for nome, sha256 in self.manifesto.arquivos
            ],
            baselines=[
                BaselineDaExecucao(
                    competencia=competencia,
                    arquivo=self.manifesto.baselines[competencia][0],
                    sha256=self.manifesto.baselines[competencia][1],
                )
                for competencia in competencias
            ],
        )

    def vendas_historicas(self, competencias: Sequence[str]) -> Decimal:
        """O total de vendas das competências, em centavos, antes de qualquer escala."""
        self._conferir(competencias)
        return total_de_vendas(self._vendas_do_periodo(competencias))

    def vendas_por_linha(
        self, competencias: Sequence[str], meta_venda: float | None
    ) -> dict[tuple[str, str], Decimal]:
        """O total vendido de cada matrícula em cada competência, por ``(competencia,
        matricula)``, somado em qualquer loja ou marca e sem arredondar: a linha do detalhamento
        arredonda a soma uma vez.

        São as vendas sobre as quais a execução apurou as comissões: as históricas, ou, na meta, as
        escaladas pelo mesmo fator da reapuração do baseline. Uma matrícula sem venda no mês não
        tem chave."""
        self._conferir(competencias)
        vendas: Sequence[Registro] = self._vendas_do_periodo(competencias)
        if meta_venda is not None:
            try:
                fator = fator_de_escala(meta_venda, total_de_vendas(vendas))
                vendas = escalar_vendas(vendas, fator)
            except MetaVendaError as erro:
                raise ReapuracaoNaMetaError(type(erro).__name__) from erro
        totais: dict[tuple[str, str], Decimal] = {}
        for venda in vendas:
            chave = (str(venda["competencia"]), str(venda["matricula"]))
            totais[chave] = totais.get(chave, Decimal(0)) + Decimal(str(venda["vlr_venda"]))
        return totais

    def baseline_na_meta(self, competencias: Sequence[str], meta_venda: float) -> Decimal:
        """O total do baseline reapurado sobre as vendas escaladas até a meta, somado em
        centavos exatos, a mesma aritmética do harness."""
        return total_das_linhas(self.linhas_na_meta(competencias, meta_venda))

    def linhas_na_meta(self, competencias: Sequence[str], meta_venda: float) -> LinhasDoBaseline:
        """O baseline reapurado sobre as vendas escaladas até a meta, linha a linha, indexado
        como o congelado: é contra ele que o detalhamento de uma execução na meta é conferido
        (T-262)."""
        try:
            self._conferir(competencias)
            vendas = self._vendas_do_periodo(competencias)
            fator = fator_de_escala(meta_venda, total_de_vendas(vendas))
            linhas = reapurar_baseline(
                self.rh,
                escalar_vendas(vendas, fator),
                self.comissoes,
                self.eventos_rh,
                self.regras,
                competencias,
            )
            indexadas = indexar_linhas(linhas)
        except (
            CompetenciaSemBaselineError,
            MetaVendaError,
            RegraBaseError,
            AssercaoVioladaError,
            BaselineIndisponivelError,
        ) as erro:
            raise ReapuracaoNaMetaError(type(erro).__name__) from erro
        # Uma competência sem nenhuma linha reapurada continua no período, como no congelado.
        return {competencia: indexadas.get(competencia, {}) for competencia in competencias}

    def _conferir(self, competencias: Sequence[str]) -> None:
        faltando = [c for c in competencias if c not in self.competencias]
        if faltando or not competencias or len(set(competencias)) != len(competencias):
            raise CompetenciaSemBaselineError(f"competências fora das bases: {list(competencias)}")

    def _vendas_do_periodo(self, competencias: Sequence[str]) -> list[Registro]:
        periodo = set(competencias)
        return [venda for venda in self.vendas if venda.get("competencia") in periodo]


@lru_cache
def carregar_bases() -> BasesDoWorker:
    """Lê e confere as bases uma vez. A subida do worker chama isto, para que um arquivo ausente
    ou adulterado derrube o processo ali, e não no primeiro job na meta."""
    return ler_bases(localizar().parent)


def ler_bases(diretorio: Path) -> BasesDoWorker:
    try:
        manifesto = json.loads(
            (diretorio / "baselines" / "manifesto.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as erro:
        raise BasesIndisponiveisError(f"manifesto.json ilegível em {diretorio}") from erro
    fontes = manifesto.get("fontes_sha256") if isinstance(manifesto, dict) else None
    baselines = manifesto.get("baselines") if isinstance(manifesto, dict) else None
    if not isinstance(fontes, dict) or not isinstance(baselines, dict) or not baselines:
        raise BasesIndisponiveisError("manifesto.json não registra as fontes e os baselines")
    versao, congelamento = _identificacao(manifesto)

    registros = {nome: _ler(diretorio / nome, fontes.get(nome)) for nome in ARQUIVOS}
    return BasesDoWorker(
        competencias=frozenset(baselines),
        rh=registros["rh.jsonl"],
        vendas=registros["vendas.jsonl"],
        comissoes=registros["comissoes.jsonl"],
        eventos_rh=registros["eventos_rh.jsonl"],
        regras=registros["regras_competencia.jsonl"],
        manifesto=ManifestoDasBases(
            versao=versao,
            congelamento=congelamento,
            # Só chega aqui o sha256 que `_ler` conferiu contra o arquivo.
            arquivos=tuple((nome, str(fontes[nome])) for nome in ARQUIVOS),
            baselines={
                competencia: _baseline_registrado(competencia, registro)
                for competencia, registro in baselines.items()
            },
        ),
    )


def _identificacao(manifesto: Mapping[str, object]) -> tuple[int, str]:
    """A versão e a data de congelamento, recusadas na subida se não couberem no registro."""
    versao = manifesto.get("versao")
    if isinstance(versao, bool) or not isinstance(versao, int) or versao < 1:
        raise BasesIndisponiveisError("manifesto.json sem versão válida")
    congelamento = manifesto.get("congelamento")
    if not isinstance(congelamento, str) or not _data_iso(congelamento):
        raise BasesIndisponiveisError("manifesto.json sem data de congelamento válida")
    return versao, congelamento


def _data_iso(texto: str) -> bool:
    try:
        return date.fromisoformat(texto).isoformat() == texto
    except ValueError:
        return False


def _baseline_registrado(competencia: object, registro: object) -> tuple[str, str]:
    arquivo = registro.get("arquivo") if isinstance(registro, dict) else None
    sha256 = registro.get("sha256") if isinstance(registro, dict) else None
    if (
        not isinstance(arquivo, str)
        or not arquivo
        or not isinstance(sha256, str)
        or not _SHA256.fullmatch(sha256)
    ):
        raise BasesIndisponiveisError(
            f"{competencia}: o manifesto não registra o arquivo e o sha256 do baseline"
        )
    return arquivo, sha256


def _ler(arquivo: Path, sha256: object) -> tuple[Registro, ...]:
    try:
        conteudo = arquivo.read_bytes()
    except OSError as erro:
        raise BasesIndisponiveisError(f"{arquivo.name} ilegível") from erro
    if hashlib.sha256(conteudo).hexdigest() != sha256:
        raise BasesIndisponiveisError(
            f"{arquivo.name} difere do sha256 registrado no manifesto dos baselines"
        )
    linhas: list[Registro] = []
    for numero, texto in enumerate(conteudo.decode("utf-8").splitlines(), start=1):
        if not texto.strip():
            continue
        linha = json.loads(texto, parse_constant=_recusar_constante)
        if not isinstance(linha, dict):
            raise BasesIndisponiveisError(f"{arquivo.name}, linha {numero}: esperado objeto")
        linhas.append(linha)
    return tuple(linhas)


def _recusar_constante(constante: str) -> NoReturn:
    # json.loads aceita NaN e Infinity por padrão; nenhum deles é dado válido aqui.
    raise BasesIndisponiveisError(f"valor não finito nas bases: {constante}")
