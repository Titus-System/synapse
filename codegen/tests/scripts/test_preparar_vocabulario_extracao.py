import json
from pathlib import Path

from scripts.preparar_vocabulario_extracao import preparar_vocabulario_extracao

_COMPONENTE = Path(__file__).resolve().parents[2]
_ORIGEM = _COMPONENTE.parent / "worker" / "sandbox" / "data" / "domrock"
_RECURSO = _COMPONENTE / "app" / "extracao" / "vocabulario.json"


def test_vocabulario_embutido_e_reproduzivel(tmp_path: Path) -> None:
    primeiro = tmp_path / "primeiro.json"
    segundo = tmp_path / "segundo.json"

    preparar_vocabulario_extracao(_ORIGEM, primeiro)
    preparar_vocabulario_extracao(_ORIGEM, segundo)

    assert primeiro.read_bytes() == segundo.read_bytes() == _RECURSO.read_bytes()
    vocabulario = json.loads(_RECURSO.read_bytes())
    assert vocabulario["marca"]["10"] == ["PRETO"]
    assert "ASSISTENTE DE VENDAS" in vocabulario["cargo"]["300"]
    assert set(vocabulario["cargo"]["150"]) == {"GERENTE DE LOJA", "GERENTE QUIOSQUE"}
    assert vocabulario["competencias_publicadas"] == [
        "2025-08",
        "2025-09",
        "2025-10",
        "2025-11",
        "2025-12",
    ]
