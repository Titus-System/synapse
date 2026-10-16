"""As bases da apuração que o worker mantém por conta própria (T-270).

Com meta de venda, o container escala as vendas até a meta e reapura o baseline sobre elas
antes de chamar a regra (``app/sandbox/escalonamento.py``). Esse baseline não tem total
congelado com que ser conferido, e o que volta do container não se valida sozinho: a regra
divide o processo com o harness e alcança o baseline que ele guarda. O worker então faz a mesma
reapuração aqui, sobre a própria cópia das bases, e é esse total que confere o
``totais.baseline`` devolvido, como o congelado confere o de uma execução sem meta
(``app/execucao/baseline.py``).

Daqui também sai ``totais.vendas_historicas`` de toda execução com sucesso: o total de vendas
das competências, lido de uma fonte que o código gerado não alcança, como o orçamento.

Só stdlib: o motor de apuração (``app/sandbox/regras_competencia.py`` e o que ele importa) não
usa pandas, e o processo do worker não o carrega (``test_isolamento_harness.py``). Cada arquivo é
conferido contra o sha256 que o manifesto dos baselines registra em ``fontes_sha256``: são as
mesmas bases de que os baselines congelados e a imagem do sandbox saíram.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import NoReturn

from app.execucao.baseline import CompetenciaSemBaselineError, localizar
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


class BasesIndisponiveisError(RuntimeError):
    """As bases não estão ao alcance do worker, ou não são as que o manifesto registra."""


class ReapuracaoNaMetaError(ValueError):
    """O baseline na meta não pôde ser reapurado: o comando pede uma competência sem bases, ou a
    meta não se aplica às vendas do período. Não é falha da regra, que nem chegou a rodar."""


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

    def vendas_historicas(self, competencias: Sequence[str]) -> Decimal:
        """O total de vendas das competências, em centavos, antes de qualquer escala."""
        self._conferir(competencias)
        return total_de_vendas(self._vendas_do_periodo(competencias))

    def baseline_na_meta(self, competencias: Sequence[str], meta_venda: float) -> Decimal:
        """O total do baseline reapurado sobre as vendas escaladas até a meta, somado em
        centavos exatos, a mesma aritmética do harness."""
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
        except (
            CompetenciaSemBaselineError,
            MetaVendaError,
            RegraBaseError,
            AssercaoVioladaError,
        ) as erro:
            raise ReapuracaoNaMetaError(type(erro).__name__) from erro
        return sum((Decimal(str(linha["comissao"])) for linha in linhas), Decimal(0))

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

    registros = {nome: _ler(diretorio / nome, fontes.get(nome)) for nome in ARQUIVOS}
    return BasesDoWorker(
        competencias=frozenset(baselines),
        rh=registros["rh.jsonl"],
        vendas=registros["vendas.jsonl"],
        comissoes=registros["comissoes.jsonl"],
        eventos_rh=registros["eventos_rh.jsonl"],
        regras=registros["regras_competencia.jsonl"],
    )


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
