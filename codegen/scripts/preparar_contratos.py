from pathlib import Path
from shutil import copyfile


def preparar_contratos() -> None:
    componente = Path(__file__).resolve().parents[1]
    origem = componente.parent / "contracts" / "domain"
    destino = componente / "contracts" / "domain"
    destino.mkdir(parents=True, exist_ok=True)
    for nome in (
        "representacao-regra.schema.json",
        "regra-nucleo.schema.json",
        "regra-especificacoes.schema.json",
        "comum.schema.json",
    ):
        copyfile(origem / nome, destino / nome)


if __name__ == "__main__":
    preparar_contratos()
