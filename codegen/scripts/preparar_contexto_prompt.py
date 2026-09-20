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
_SCHEMAS_REGRA = (
    "representacao-regra.schema.json",
    "regra-nucleo.schema.json",
    "regra-especificacoes.schema.json",
)
_SECOES_CONTRATO = (
    "## A assinatura",
    "## `RegraFn`: o contrato de entrada e saída",
    "## Regras da entrada",
    "## Convenção de tipos das colunas",
    "## Como o código declara o elemento que implementa",
    "## Bibliotecas permitidas no sandbox",
)
_RASTREAVEL = r"T-\d+|DEC-\d+|CANONICAL_MANAGER_RATE"
# O prompt viaja sozinho: nenhum arquivo do monorepo chega junto para o agente abrir.
_REFERENCIAS_INTERNAS = (
    (r"\s*O exemplo completo, testado e validado, está em\s+\[[^\]]+\]\([^)]+\)\.", ""),
    (r"\s*Verificado em\s+`testar-contrato\.py`\.", ""),
    (r"\s*\(`worker/sandbox/data/domrock/schema\.json`\)", ""),
    (r"\s+- ver\s+`worker/app/sandbox/regras_base\.py`[^)]+gerado\)", ")"),
    (
        r" - exatamente como no exemplo\s+\(`[^`]+`\), onde\s+`_MARCA_ALVO`,\s+`_CARGO_ALVO` e"
        r"\s+`_PERCENTUAL` são\s+valores fixos escritos pelo agente, não parâmetros da função\.",
        ": valores fixos escritos pelo agente, não parâmetros da função.",
    ),
    (r"o validador\s+de saída \(`validar-saida\.py`\)", "o validador de saída"),
    (r"\s*- ver ARCHITECTURE\.md\s+§[\d.]+, \"a regra é simulada por inteiro\"", ""),
    (r" \(ARCHITECTURE\.md §[\d.]+\)", ""),
)


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
    texto = re.sub(rf"\s*\((?:{_RASTREAVEL})(?:/(?:{_RASTREAVEL}))*\)", "", texto)
    texto = re.sub(rf"\s+d[ao] (?:{_RASTREAVEL})\b", "", texto)
    return re.sub(rf"(?: -)? ?\b(?:{_RASTREAVEL})\b", "", texto).strip()


def _sem_referencias_internas(texto: str) -> str:
    for padrao, substituto in _REFERENCIAS_INTERNAS:
        texto = re.sub(padrao, substituto, texto)
    return texto


def _para_prompt(texto: str) -> str:
    return _sem_referencias_internas(_sem_rastreabilidade(texto))


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
            valor = _para_prompt(valor)
        resultado[chave] = valor
    return resultado


def _secoes(documento: str) -> dict[str, str]:
    partes = re.split(r"^(## .+)$", documento, flags=re.MULTILINE)
    return dict(zip(partes[1::2], partes[2::2], strict=True))


def preparar_contrato_regrafn(origem: Path, destino: Path) -> None:
    secoes = _secoes(origem.read_text(encoding="utf-8"))
    ausentes = [titulo for titulo in _SECOES_CONTRATO if titulo not in secoes]
    if ausentes:
        raise ValueError(f"Seções ausentes no contrato do harness: {', '.join(ausentes)}")
    contrato = "\n\n".join((titulo + secoes[titulo]).strip() for titulo in _SECOES_CONTRATO)
    destino.write_text(
        _para_prompt(contrato) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def preparar_schemas_regra(origem: Path, destino: Path) -> None:
    bundle = {
        nome: _esquema_para_prompt(
            simplejson.loads((origem / nome).read_text(encoding="utf-8"), use_decimal=True)
        )
        for nome in _SCHEMAS_REGRA
    }
    destino.write_text(
        simplejson.dumps(bundle, sort_keys=True, indent=2, ensure_ascii=False, use_decimal=True)
        + "\n",
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
    preparar_schemas_regra(
        componente.parent / "contracts" / "domain",
        componente / "app" / "prompts" / "regra_schemas.json",
    )
    preparar_contexto_prompt(
        componente.parent / "worker" / "sandbox" / "data" / "domrock",
        componente / "app" / "prompts" / "contexto_bases.json",
    )
