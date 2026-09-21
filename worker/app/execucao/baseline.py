"""Os baselines congelados que o worker mantém por conta própria (T-066).

A imagem do sandbox carrega os mesmos arquivos (T-033), e o harness soma deles o
``totais.baseline`` que sai no envelope. O worker precisa da própria cópia porque o número que
volta do container não se valida sozinho: a regra divide o processo com o harness (T-034) e
alcança o que ele guarda. Conferir o total devolvido contra o que o worker leu por conta
própria é o que denuncia adulteração ou descompasso antes de o número ser julgado.

Só stdlib: ``app/sandbox/carga.py`` lê os mesmos arquivos, mas importa pandas, e o processo
do worker não o carrega (``test_isolamento_harness.py``).

Os arquivos ficam em ``sandbox/data/domrock/baselines`` a partir da raiz do worker: ``worker/``
no repositório, ``/app`` na imagem (o ``worker/Dockerfile`` os copia para lá).
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

CAMINHO_RELATIVO = Path("sandbox") / "data" / "domrock" / "baselines"
CENTAVO = Decimal("0.01")


class BaselineIndisponivelError(RuntimeError):
    """Os baselines não estão ao alcance do worker, ou não são os que o manifesto registra."""


class CompetenciaSemBaselineError(KeyError):
    """O job pede uma competência que não tem baseline congelado."""


@dataclass(frozen=True)
class BaselinesCongelados:
    """O total de cada competência, exato em centavos."""

    por_competencia: Mapping[str, Decimal]

    def total(self, competencias: Sequence[str]) -> Decimal:
        """A soma do período, na mesma aritmética do harness: centavos exatos somados.

        Uma competência sem baseline é defeito do comando, não da regra: a imagem também não
        a tem, e o harness teria falhado antes de escrever qualquer envelope.
        """
        faltando = [c for c in competencias if c not in self.por_competencia]
        if faltando:
            raise CompetenciaSemBaselineError(f"competências sem baseline congelado: {faltando}")
        return sum((self.por_competencia[c] for c in competencias), Decimal(0))


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
    for competencia, esperado in registrados.items():
        totais[competencia] = _conferir_competencia(diretorio, competencia, esperado)
    return BaselinesCongelados(por_competencia=totais)


def _conferir_competencia(diretorio: Path, competencia: str, esperado: Any) -> Decimal:
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

    comissoes = _comissoes_por_matricula(conteudo, competencia, arquivo.name)
    if len(comissoes) != esperado.get("matriculas"):
        raise BaselineIndisponivelError(
            f"{competencia}: {len(comissoes)} matrículas, "
            f"o manifesto registra {esperado.get('matriculas')}"
        )
    total = sum(comissoes, Decimal(0))
    if total != _decimal(esperado.get("total"), f"{competencia}: total do manifesto"):
        raise BaselineIndisponivelError(
            f"{competencia}: as matrículas somam {total}, "
            f"o manifesto registra {esperado.get('total')}"
        )
    return total


def _comissoes_por_matricula(conteudo: bytes, competencia: str, nome: str) -> list[Decimal]:
    comissoes: list[Decimal] = []
    vistas: set[object] = set()
    for numero, texto in enumerate(conteudo.decode("utf-8").splitlines(), start=1):
        if not texto.strip():
            continue
        linha = json.loads(texto)
        if linha.get("nivel") != "matricula":
            continue
        origem = f"{nome}, linha {numero}"
        if linha.get("competencia") != competencia:
            raise BaselineIndisponivelError(f"{origem}: competência diferente de {competencia}")
        matricula = linha.get("matricula")
        if matricula in vistas:
            raise BaselineIndisponivelError(f"{origem}: matrícula repetida")
        vistas.add(matricula)
        comissoes.append(_decimal(linha.get("comissao"), f"{origem}: comissão"))
    return comissoes


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
