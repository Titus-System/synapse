from pathlib import Path
from shutil import copyfile


def preparar_contratos() -> None:
    componente = Path(__file__).resolve().parents[1]
    origem = componente.parent / "contracts" / "domain"
    destino = componente / "contracts" / "domain"
    esquemas = {arquivo.name: arquivo for arquivo in origem.glob("*.schema.json")}
    if not esquemas:
        raise FileNotFoundError("Contratos de domínio ausentes na fonte de build")
    destino.mkdir(parents=True, exist_ok=True)
    for nome, esquema in esquemas.items():
        copyfile(esquema, destino / nome)
    for incorporado in destino.glob("*.schema.json"):
        if incorporado.name not in esquemas:
            incorporado.unlink()


if __name__ == "__main__":
    preparar_contratos()
