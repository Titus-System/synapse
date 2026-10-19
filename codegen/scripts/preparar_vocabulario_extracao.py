"""Gera o vocabulário embutido exclusivamente a partir do dataset canônico."""

from collections import defaultdict
from pathlib import Path

import json


def preparar_vocabulario_extracao(origem: Path, destino: Path) -> None:
    schema = json.loads((origem / "schema.json").read_text(encoding="utf-8"))
    nomes: dict[str, dict[str, set[str]]] = {
        campo: defaultdict(set) for campo in ("loja", "marca", "cargo")
    }
    for linha in (origem / "rh.jsonl").read_text(encoding="utf-8").splitlines():
        registro = json.loads(linha)
        for campo, codigos in nomes.items():
            codigos[str(registro[f"cod_{campo}"])].add(registro[f"descr_{campo}"])
    vocabulario = {
        **{
            campo: {
                codigo: sorted(descricoes)
                for codigo, descricoes in sorted(codigos.items(), key=lambda item: int(item[0]))
            }
            for campo, codigos in nomes.items()
        },
        "competencias_publicadas": sorted(set(schema["published_competencias"])),
    }
    destino.write_text(
        json.dumps(vocabulario, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    raiz = Path(__file__).resolve().parents[2]
    preparar_vocabulario_extracao(
        raiz / "worker" / "sandbox" / "data" / "domrock",
        raiz / "codegen" / "app" / "extracao" / "vocabulario.json",
    )
