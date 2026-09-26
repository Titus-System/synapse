"""Prepara e verifica os cinco baselines congelados; nunca executa código gerado.

Uso na pasta worker: python -m scripts.build_baselines [--check].
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from app.sandbox.assercoes import TabelaApurada
from app.sandbox.regras_competencia import apurar_vigente

WORKER_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = WORKER_ROOT / "sandbox" / "data" / "domrock"
EVENTOS_FONTE = WORKER_ROOT.parent / "dataset_rh" / "eventos_rh.jsonl"
COMPETENCIAS = ("2025-08", "2025-09", "2025-10", "2025-11", "2025-12")
AVISO = "Baseline não é gabarito: é nossa apuração da regra vigente, não o valor pago pela empresa."


def ler_jsonl(path: Path) -> list[dict[str, object]]:
    registros = []
    for numero, linha in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not linha.strip():
            continue
        valor = json.loads(linha)
        if not isinstance(valor, dict):
            raise ValueError(f"{path.name}, linha {numero}: esperado objeto")
        registros.append(valor)
    return registros


def ler_eventos_fonte(path: Path) -> list[dict[str, object]]:
    """A T-028 versionou objetos multiline e comentários em um arquivo .jsonl.

    Remove apenas comentários fora de strings e preserva todos os valores/IDs.
    Eventos repetidos em meses diferentes continuam distintos; T-030 une dias.
    """
    conteudo = path.read_text(encoding="utf-8-sig")
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/')
    conteudo = tokens.sub(lambda m: m[0] if m[0].startswith('"') else " ", conteudo)
    decoder = json.JSONDecoder()
    eventos: list[dict[str, object]] = []
    ids: set[str] = set()
    while conteudo.strip():
        valor, posicao = decoder.raw_decode(conteudo.lstrip())
        conteudo = conteudo.lstrip()[posicao:]
        if not isinstance(valor, dict) or not isinstance(valor.get("id"), str):
            raise ValueError("evento RH deve ser objeto com id")
        if valor["id"] in ids:
            raise ValueError(f"id de evento RH duplicado: {valor['id']}")
        ids.add(valor["id"])
        eventos.append(valor)
    return sorted(
        eventos,
        key=lambda e: (str(e.get("competencia_origem")), str(e.get("matricula")), str(e["id"])),
    )


def _json(objeto: object, *, compacto: bool = False) -> bytes:
    return (
        json.dumps(
            objeto,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":") if compacto else None,
            indent=None if compacto else 2,
        )
        + "\n"
    ).encode("utf-8")


def _jsonl(linhas: list[dict[str, object]]) -> bytes:
    return b"".join(_json(linha, compacto=True) for linha in linhas)


def _hash(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def _linhas_auditoria(tabela: TabelaApurada) -> list[dict[str, object]]:
    resultado = tabela.resultado_apuracao
    competencia = resultado["competencia"]
    lojas = resultado["por_loja"]
    if lojas is None or resultado["status"] != "sucesso":
        raise ValueError(f"{competencia}: não se congela apuração inválida")
    modelo: dict[str, object] = {
        "competencia": competencia,
        "nivel": "total",
        "matricula": None,
        "cod_loja": None,
        "loja": None,
        "cargo": None,
        "base_calculo": None,
        "comissao": resultado["total"],
        "rastreabilidade": None,
        "assercoes": resultado["assercoes"],
    }
    registros = [modelo]
    nomes_lojas = {str(linha["cod_loja"]): linha["loja"] for linha in tabela}
    for loja, valor in sorted(lojas.items(), key=lambda item: int(item[0])):
        registros.append(
            {
                **modelo,
                "nivel": "loja",
                "cod_loja": int(loja),
                "loja": nomes_lojas[loja],
                "comissao": valor,
                "assercoes": None,
            }
        )
    for linha in tabela:
        registros.append({**modelo, **linha, "nivel": "matricula", "assercoes": None})
    return registros


def _marca_unica_da_rastreabilidade(linha: Mapping[str, object], competencia: str) -> int:
    rastreabilidade = linha.get("rastreabilidade")
    chaves = rastreabilidade.get("chaves_comissao") if isinstance(rastreabilidade, dict) else None
    if not isinstance(chaves, list) or not chaves:
        raise ValueError(
            f"{competencia}/{linha.get('matricula')}: "
            "rastreabilidade.chaves_comissao ausente ou vazia"
        )
    marcas = {chave.get("cod_marca") for chave in chaves if isinstance(chave, dict)}
    if len(marcas) != 1:
        raise ValueError(
            f"{competencia}/{linha.get('matricula')}: esperado exatamente uma cod_marca; "
            f"rastreabilidade contém {len(marcas)} marcas"
        )
    (marca,) = marcas
    if not isinstance(marca, int) or isinstance(marca, bool):
        raise ValueError(
            f"{competencia}/{linha.get('matricula')}: cod_marca da rastreabilidade não é inteiro"
        )
    return marca


def _linhas_apuracao_base(
    tabela: TabelaApurada, rh: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Publica o baseline exatamente na forma do contrato T-034.

    ``cod_marca`` vem do RH por competência + matrícula. A rastreabilidade do cálculo
    precisa apontar para exatamente a mesma marca; se um cálculo passar a envolver
    múltiplas marcas para a mesma matrícula, o congelamento falha explicitamente em vez
    de escolher uma delas em silêncio.
    """
    competencia = str(tabela.resultado_apuracao["competencia"])
    pessoas: dict[str, Mapping[str, object]] = {}
    for registro in rh:
        if registro.get("competencia") != competencia:
            continue
        matricula = registro.get("matricula")
        if not isinstance(matricula, str) or not matricula:
            raise ValueError(f"{competencia}: matrícula inválida no RH")
        if matricula in pessoas:
            raise ValueError(f"{competencia}: matrícula repetida no RH: {matricula}")
        pessoas[matricula] = registro

    registros: list[dict[str, object]] = []
    vistas: set[str] = set()
    for linha in tabela:
        matricula = linha.get("matricula")
        if not isinstance(matricula, str) or not matricula:
            raise ValueError(f"{competencia}: matrícula inválida na apuração")
        if matricula in vistas:
            raise ValueError(f"{competencia}: matrícula repetida na apuração: {matricula}")
        vistas.add(matricula)
        pessoa = pessoas.get(matricula)
        if pessoa is None:
            raise ValueError(f"{competencia}/{matricula}: matrícula ausente no RH")

        cod_loja = pessoa.get("cod_loja")
        cod_marca = pessoa.get("cod_marca")
        cod_cargo = pessoa.get("cod_cargo")
        if not all(
            isinstance(v, int) and not isinstance(v, bool) for v in (cod_loja, cod_marca, cod_cargo)
        ):
            raise ValueError(f"{competencia}/{matricula}: dimensões do RH devem ser inteiras")
        if linha.get("cod_loja") != cod_loja or linha.get("cargo") != cod_cargo:
            raise ValueError(f"{competencia}/{matricula}: loja/cargo da apuração divergem do RH")
        marca_rastreada = _marca_unica_da_rastreabilidade(linha, competencia)
        if marca_rastreada != cod_marca:
            raise ValueError(
                f"{competencia}/{matricula}: cod_marca da rastreabilidade ({marca_rastreada}) "
                f"difere do RH ({cod_marca})"
            )
        registros.append(
            {
                "matricula": matricula,
                "cod_loja": cod_loja,
                "cod_marca": cod_marca,
                "cod_cargo": cod_cargo,
                "competencia": competencia,
                "comissao": linha.get("comissao"),
            }
        )
    return registros


def gerar_artefatos(
    data_dir: Path = DATA_DIR,
    eventos_fonte: Path = EVENTOS_FONTE,
) -> dict[str, bytes]:
    """Calcula tudo e valida antes de escrever qualquer arquivo."""
    schema = json.loads((data_dir / "schema.json").read_text(encoding="utf-8"))
    if schema.get("published_competencias") != list(COMPETENCIAS):
        raise ValueError("dataset deve publicar exatamente as cinco competências Ago-Dez/2025")
    relatorio = json.loads((data_dir / "normalization_report.json").read_text(encoding="utf-8"))
    for competencia in COMPETENCIAS:
        status = relatorio.get("competency_status", {}).get(competencia, {})
        if status.get("status") != "ready" or status.get("published") is not True:
            raise ValueError(f"competência não pronta na T-026: {competencia}")
    rh = ler_jsonl(data_dir / "rh.jsonl")
    vendas = ler_jsonl(data_dir / "vendas.jsonl")
    taxas = ler_jsonl(data_dir / "comissoes.jsonl")
    regras = ler_jsonl(data_dir / "regras_competencia.jsonl")
    eventos = ler_eventos_fonte(eventos_fonte)
    artefatos = {"eventos_rh.jsonl": _jsonl(eventos)}
    resumos: dict[str, object] = {}
    for competencia in COMPETENCIAS:
        tabela = apurar_vigente(rh, vendas, taxas, eventos, competencia, regras=regras)
        if not isinstance(tabela, TabelaApurada):
            raise TypeError("preparação exige a tabela validada pela T-031")
        nome = f"baselines/baseline-{competencia}.jsonl"
        conteudo = _jsonl(_linhas_apuracao_base(tabela, rh))
        artefatos[nome] = conteudo

        nome_auditoria = f"baselines/auditoria/baseline-{competencia}.jsonl"
        conteudo_auditoria = _jsonl(_linhas_auditoria(tabela))
        artefatos[nome_auditoria] = conteudo_auditoria

        resumos[competencia] = {
            "arquivo": nome,
            "sha256": _hash(conteudo),
            "arquivo_auditoria": nome_auditoria,
            "sha256_auditoria": _hash(conteudo_auditoria),
            "matriculas": len(tabela),
            "total": tabela.resultado_apuracao["total"],
            "assercoes": tabela.resultado_apuracao["assercoes"],
        }
    fontes = {
        nome: _hash((data_dir / nome).read_bytes())
        for nome in (
            "rh.jsonl",
            "vendas.jsonl",
            "comissoes.jsonl",
            "schema.json",
            "normalization_report.json",
            "regras_competencia.jsonl",
        )
    }
    fontes["eventos_rh_fonte"] = _hash(eventos_fonte.read_bytes())
    fontes["eventos_rh.jsonl"] = _hash(artefatos["eventos_rh.jsonl"])
    motor = {
        nome: _hash((WORKER_ROOT / nome).read_bytes())
        for nome in (
            "app/sandbox/regras_base.py",
            "app/sandbox/assercoes.py",
            "app/sandbox/ajustes_competencia.py",
            "app/sandbox/regras_competencia.py",
            "scripts/build_baselines.py",
        )
    }
    artefatos["baselines/manifesto.json"] = _json(
        {
            "versao": 2,
            "congelamento": "2026-09-17",
            "aviso": AVISO,
            "competencias": list(COMPETENCIAS),
            "fontes_sha256": fontes,
            "motor_sha256": motor,
            "baselines": resumos,
        }
    )
    return artefatos


def build_baselines(
    *,
    data_dir: Path = DATA_DIR,
    eventos_fonte: Path = EVENTOS_FONTE,
    output_dir: Path | None = None,
    check: bool = False,
    atualizar: bool = False,
) -> Mapping[str, bytes]:
    destino = data_dir if output_dir is None else output_dir
    artefatos = gerar_artefatos(data_dir, eventos_fonte)
    diferentes = [
        nome
        for nome, dados in artefatos.items()
        if not (destino / nome).is_file() or (destino / nome).read_bytes() != dados
    ]
    congelado = (destino / "baselines" / "manifesto.json").is_file()
    if diferentes and (check or (congelado and not atualizar)):
        raise ValueError(
            "baseline congelado ausente/divergente: "
            + ", ".join(diferentes)
            + ". Investigue a mudança; --atualizar exige revisão do congelamento e de T-036/T-076."
        )
    if not check:
        for nome, dados in artefatos.items():
            path = destino / nome
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(dados)
    return artefatos


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--eventos-fonte", type=Path, default=EVENTOS_FONTE)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check", action="store_true", help="compara bytes sem escrever")
    parser.add_argument("--atualizar", action="store_true", help="recongela após revisão explícita")
    args = parser.parse_args()
    artefatos = build_baselines(
        data_dir=args.data_dir,
        eventos_fonte=args.eventos_fonte,
        output_dir=args.output_dir,
        check=args.check,
        atualizar=args.atualizar,
    )
    manifesto = json.loads(artefatos["baselines/manifesto.json"])
    for competencia, resumo in cast(dict[str, dict[str, object]], manifesto["baselines"]).items():
        print(f"{competencia}: {resumo['matriculas']} matrículas, total R$ {resumo['total']}")
    print(AVISO)


if __name__ == "__main__":
    main()
