"""Os baselines congelados que o worker mantém por conta própria (T-066, T-262).

A imagem do sandbox carrega os mesmos arquivos (T-033), e o harness soma deles o
``totais.baseline`` que sai no envelope. O worker precisa da própria cópia porque o número que
volta do container não se valida sozinho: a regra divide o processo com o harness (T-034) e
alcança o que ele guarda. Conferir o total devolvido contra o que o worker leu por conta
própria é o que denuncia adulteração ou descompasso antes de o número ser julgado. As linhas,
indexadas por competência e matrícula, conferem o detalhamento do resultado (T-262).

Só stdlib: ``app/sandbox/carga.py`` lê os mesmos arquivos, mas importa pandas, e o processo
do worker não o carrega (``test_isolamento_harness.py``).

Os arquivos ficam em ``sandbox/data/domrock/baselines`` a partir da raiz do worker: ``worker/``
no repositório, ``/app`` na imagem (o ``worker/Dockerfile`` os copia para lá).
"""

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

CAMINHO_RELATIVO = Path("sandbox") / "data" / "domrock" / "baselines"
CENTAVO = Decimal("0.01")
# As colunas de ``apuracao_base`` (contracts/harness/README.md), que são também as do baseline
# T-032 em disco. Repetidas aqui porque ``app/sandbox/carga.py`` importa pandas.
COLUNAS_DO_CONTRATO = frozenset(
    {"matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia", "comissao"}
)


class BaselineIndisponivelError(RuntimeError):
    """Os baselines não estão ao alcance do worker, ou não são os que o manifesto registra."""


class CompetenciaSemBaselineError(KeyError):
    """O job pede uma competência que não tem baseline congelado."""


class LinhaDoBaseline(NamedTuple):
    """Uma matrícula numa competência, como o harness a indexa em ``apuracao_base``: códigos como
    texto e comissão exata em centavos."""

    cod_loja: str
    cod_marca: str
    cod_cargo: str
    comissao: Decimal


# Competência, depois matrícula: o mesmo aninhamento do detalhamento do resultado.
type LinhasDoBaseline = Mapping[str, Mapping[str, LinhaDoBaseline]]


@dataclass(frozen=True)
class BaselinesCongelados:
    """O total e as linhas de cada competência, exatos em centavos."""

    por_competencia: Mapping[str, Decimal]
    linhas: LinhasDoBaseline = field(default_factory=dict, repr=False)

    def total(self, competencias: Sequence[str]) -> Decimal:
        """A soma do período, na mesma aritmética do harness: centavos exatos somados.

        Uma competência sem baseline é defeito do comando, não da regra: a imagem também não
        a tem, e o harness teria falhado antes de escrever qualquer envelope.
        """
        self._conferir(competencias, self.por_competencia)
        return sum((self.por_competencia[c] for c in competencias), Decimal(0))

    def linhas_do_periodo(self, competencias: Sequence[str]) -> LinhasDoBaseline:
        """As linhas das competências do job, contra as quais o detalhamento é conferido."""
        self._conferir(competencias, self.linhas)
        return {competencia: self.linhas[competencia] for competencia in competencias}

    @staticmethod
    def _conferir(competencias: Sequence[str], disponiveis: Mapping[str, object]) -> None:
        faltando = [c for c in competencias if c not in disponiveis]
        if faltando:
            raise CompetenciaSemBaselineError(f"competências sem baseline congelado: {faltando}")


def indexar_linhas(
    registros: Iterable[Mapping[str, object]],
) -> dict[str, dict[str, LinhaDoBaseline]]:
    """Linhas na forma de ``apuracao_base`` indexadas como o harness as indexa (T-035): códigos
    inteiros viram texto, e a comissão é arredondada a centavos uma vez. É também o que indexa
    o baseline reapurado na meta (``app/execucao/bases.py``), para os dois serem conferidos do
    mesmo jeito."""
    linhas: dict[str, dict[str, LinhaDoBaseline]] = {}
    for registro in registros:
        competencia = str(registro["competencia"])
        matricula = str(registro["matricula"])
        da_competencia = linhas.setdefault(competencia, {})
        if matricula in da_competencia:
            raise BaselineIndisponivelError(f"{competencia}: matrícula repetida no baseline")
        comissao = Decimal(str(registro["comissao"]))
        da_competencia[matricula] = LinhaDoBaseline(
            cod_loja=_codigo(registro["cod_loja"]),
            cod_marca=_codigo(registro["cod_marca"]),
            cod_cargo=_codigo(registro["cod_cargo"]),
            comissao=comissao.quantize(CENTAVO, rounding=ROUND_HALF_UP),
        )
    return linhas


def total_das_linhas(linhas: LinhasDoBaseline) -> Decimal:
    """A soma das comissões, em centavos exatos: a aritmética do ``totais.baseline`` do harness."""
    return sum(
        (linha.comissao for da_competencia in linhas.values() for linha in da_competencia.values()),
        Decimal(0),
    )


def localizar() -> Path:
    for pai in Path(__file__).resolve().parents:
        candidato = pai / CAMINHO_RELATIVO
        if (candidato / "manifesto.json").is_file():
            return candidato
    raise BaselineIndisponivelError(f"{CAMINHO_RELATIVO}/manifesto.json não encontrado")


@lru_cache
def carregar_baselines() -> BaselinesCongelados:
    """Lê e confere os baselines uma vez. A subida do worker chama isto, para que um arquivo
    ausente ou adulterado derrube o processo ali, e não no primeiro job."""
    return ler_baselines(localizar())


def ler_baselines(diretorio: Path) -> BaselinesCongelados:
    try:
        manifesto = json.loads((diretorio / "manifesto.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise BaselineIndisponivelError(f"manifesto.json ilegível em {diretorio}") from erro

    registrados = manifesto.get("baselines") if isinstance(manifesto, dict) else None
    if not isinstance(registrados, dict) or not registrados:
        raise BaselineIndisponivelError("manifesto.json não registra nenhum baseline")

    totais: dict[str, Decimal] = {}
    linhas: dict[str, Mapping[str, LinhaDoBaseline]] = {}
    for competencia, esperado in registrados.items():
        linhas[competencia] = _conferir_competencia(diretorio, competencia, esperado)
        totais[competencia] = total_das_linhas({competencia: linhas[competencia]})
    return BaselinesCongelados(por_competencia=totais, linhas=linhas)


def _conferir_competencia(
    diretorio: Path, competencia: str, esperado: Any
) -> Mapping[str, LinhaDoBaseline]:
    if not isinstance(esperado, dict):
        raise BaselineIndisponivelError(f"{competencia}: registro do manifesto inválido")
    # O manifesto registra o caminho relativo à pasta das bases ("baselines/<arquivo>").
    arquivo = diretorio / Path(str(esperado.get("arquivo", ""))).name
    try:
        conteudo = arquivo.read_bytes()
    except OSError as erro:
        raise BaselineIndisponivelError(f"{competencia}: {arquivo.name} ilegível") from erro

    if hashlib.sha256(conteudo).hexdigest() != esperado.get("sha256"):
        raise BaselineIndisponivelError(
            f"{competencia}: {arquivo.name} difere do sha256 registrado no manifesto"
        )

    registros = _registros_da_competencia(conteudo, competencia, arquivo.name)
    if len(registros) != esperado.get("matriculas"):
        raise BaselineIndisponivelError(
            f"{competencia}: {len(registros)} matrículas, "
            f"o manifesto registra {esperado.get('matriculas')}"
        )
    linhas = indexar_linhas(registros).get(competencia, {})
    total = total_das_linhas({competencia: linhas})
    if total != _decimal(esperado.get("total"), f"{competencia}: total do manifesto"):
        raise BaselineIndisponivelError(
            f"{competencia}: as matrículas somam {total}, "
            f"o manifesto registra {esperado.get('total')}"
        )
    return linhas


def _registros_da_competencia(
    conteudo: bytes, competencia: str, nome: str
) -> list[Mapping[str, object]]:
    registros: list[Mapping[str, object]] = []
    vistas: set[object] = set()
    for numero, texto in enumerate(conteudo.decode("utf-8").splitlines(), start=1):
        if not texto.strip():
            continue
        linha = json.loads(texto)
        origem = f"{nome}, linha {numero}"
        # Uma linha por matrícula, sem níveis agregados: uma coluna a mais ou a menos é o
        # formato antigo (T-032 antes do contrato) e somaria a apuração mais de uma vez.
        if not isinstance(linha, dict) or linha.keys() != COLUNAS_DO_CONTRATO:
            raise BaselineIndisponivelError(f"{origem}: colunas diferentes das do contrato")
        if linha["competencia"] != competencia:
            raise BaselineIndisponivelError(f"{origem}: competência diferente de {competencia}")
        matricula = linha["matricula"]
        if not isinstance(matricula, str) or not matricula:
            raise BaselineIndisponivelError(f"{origem}: matrícula inválida")
        if matricula in vistas:
            raise BaselineIndisponivelError(f"{origem}: matrícula repetida")
        vistas.add(matricula)
        for coluna in ("cod_loja", "cod_marca", "cod_cargo"):
            _codigo(linha[coluna], f"{origem}: {coluna}")
        _decimal(linha["comissao"], f"{origem}: comissão")
        registros.append(linha)
    return registros


def _codigo(valor: object, origem: str = "código do baseline") -> str:
    """Loja, marca ou cargo como texto, a mesma leitura do harness (``resultado._codigo_de``): o
    dataset traz inteiro, e o detalhamento traz o código como texto."""
    if isinstance(valor, int) and not isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, str) and valor:
        return valor
    raise BaselineIndisponivelError(f"{origem} não é código inteiro nem texto")


def _decimal(valor: object, origem: str) -> Decimal:
    """Um valor em reais, exato em centavos. Uma casa a mais seria arredondada de um jeito
    aqui e de outro no harness, e a conferência passaria a acusar o que não aconteceu."""
    if not isinstance(valor, int | float) or isinstance(valor, bool):
        raise BaselineIndisponivelError(f"{origem} não é numérica")
    if not math.isfinite(valor):
        raise BaselineIndisponivelError(f"{origem} não é finita")
    decimal = Decimal(str(valor))
    if decimal != decimal.quantize(CENTAVO):
        raise BaselineIndisponivelError(f"{origem} não é exata em centavos")
    return decimal
