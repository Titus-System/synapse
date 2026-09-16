from pathlib import Path
from shutil import copyfile


def preparar_contratos() -> None:
    componente = Path(__file__).resolve().parents[1]
    origem = componente.parent / "contracts"
    destino = componente / "contracts"
    esquemas = {arquivo.relative_to(origem): arquivo for arquivo in origem.rglob("*.schema.json")}
    if not esquemas:
        raise FileNotFoundError("Contratos ausentes na fonte de build")
    destino.mkdir(parents=True, exist_ok=True)
    for nome, esquema in esquemas.items():
        (destino / nome).parent.mkdir(parents=True, exist_ok=True)
        copyfile(esquema, destino / nome)
    for incorporado in destino.rglob("*.schema.json"):
        if incorporado.relative_to(destino) not in esquemas:
            incorporado.unlink()


if __name__ == "__main__":
    preparar_contratos()
