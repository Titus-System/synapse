"""Preparação local: poetry run python scripts/preparar_contexto_prompt.py.

Seleciona a primeira ocorrência de cada grupo na ordem do JSONL: cargo/descrição
no RH, presença de data real nas vendas, marca nas comissões e tipo/nulidade nos eventos.
Completa dez linhas
com as primeiras ainda não selecionadas e publica na ordem original da fonte.
Somente este script de preparação acessa os dados do sandbox.
"""

import re
from pathlib import Path
from typing import Any

import simplejson

_BASES = ("rh", "vendas", "comissoes", "eventos_rh")
_LIMITE = 10


def _grupo(base: str, registro: dict[str, Any]) -> str:
    if base == "rh":
        return simplejson.dumps([registro["cod_cargo"], registro["descr_cargo"]])
    if base == "vendas":
        return str(registro["data_venda"] is not None)
    if base == "eventos_rh":
        return simplejson.dumps(
            [registro["tipo"], registro["data_fim"] is None, registro["detalhes"] is None]
        )
    return str(registro["cod_marca"])


def _sem_rastreabilidade(texto: str) -> str:
    texto = re.sub(r"\s*\(T-\d+(?:/T-\d+)*\)", "", texto)
    return re.sub(r"(?: -)? ?\b(?:T-\d+|DEC-\d+|CANONICAL_MANAGER_RATE)\b", "", texto).strip()


def _esquema_para_prompt(esquema: dict[str, Any]) -> dict[str, Any]:
    resultado = {}
    for chave, valor in esquema.items():
        if chave in {"produced_by", "decision_id"}:
            continue
        if isinstance(valor, dict):
            valor = _esquema_para_prompt(valor)
        elif isinstance(valor, list):
            valor = [_esquema_para_prompt(v) if isinstance(v, dict) else v for v in valor]
        elif isinstance(valor, str):
            valor = _sem_rastreabilidade(valor)
        resultado[chave] = valor
    return resultado


def preparar_contrato_regrafn(origem: Path, destino: Path) -> None:
    documento = origem.read_text(encoding="utf-8")
    inicio = documento.index("## A assinatura\n")
    fim = documento.index("### Exemplo mínimo,", inicio)
    destino.write_text(
        _sem_rastreabilidade(documento[inicio:fim]).rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _selecionar_amostra(caminho: Path, base: str) -> list[dict[str, Any]]:
    primeiras: dict[int, dict[str, Any]] = {}
    representantes: dict[str, tuple[int, dict[str, Any]]] = {}
    with caminho.open(encoding="utf-8") as arquivo:
        for indice, linha in enumerate(arquivo):
            registro = simplejson.loads(linha, use_decimal=True)
            if len(primeiras) < _LIMITE:
                primeiras[indice] = registro
            grupo = _grupo(base, registro)
            if grupo not in representantes and len(representantes) < _LIMITE:
                representantes[grupo] = (indice, registro)

    selecionadas = dict(representantes.values())
    for indice, registro in primeiras.items():
        if len(selecionadas) == _LIMITE:
            break
        selecionadas.setdefault(indice, registro)
    if len(selecionadas) != _LIMITE:
        raise ValueError(f"A base {base} precisa conter pelo menos {_LIMITE} registros")
    return [selecionadas[indice] for indice in sorted(selecionadas)]


def preparar_contexto_prompt(origem: Path, destino: Path) -> None:
    esquema = simplejson.loads((origem / "schema.json").read_text(encoding="utf-8"))
    contexto = {
        base: {
            "esquema": _esquema_para_prompt(esquema["tables"][base]),
            "amostra": _selecionar_amostra(origem / f"{base}.jsonl", base),
        }
        for base in _BASES
    }
    destino.write_text(
        simplejson.dumps(contexto, sort_keys=True, indent=2, ensure_ascii=False, use_decimal=True)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    componente = Path(__file__).resolve().parents[1]
    preparar_contrato_regrafn(
        componente.parent / "contracts" / "harness" / "README.md",
        componente / "app" / "prompts" / "regrafn.md",
    )
    preparar_contexto_prompt(
        componente.parent / "worker" / "sandbox" / "data" / "domrock",
        componente / "app" / "prompts" / "contexto_bases.json",
    )
