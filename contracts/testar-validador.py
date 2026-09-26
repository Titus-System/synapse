from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


DIRETORIO_CONTRATOS = Path(__file__).resolve().parent


class TestarValidador(unittest.TestCase):
    def test_rejeita_exemplo_com_campo_invalido(self) -> None:
        with tempfile.TemporaryDirectory() as diretorio_temporario:
            diretorio_copia = Path(diretorio_temporario) / "contracts"
            shutil.copytree(DIRETORIO_CONTRATOS, diretorio_copia)
            caminho_exemplo = diretorio_copia / "examples/domain/consumo-tokens.json"

            with caminho_exemplo.open(encoding="utf-8") as arquivo:
                exemplo = json.load(arquivo)
            exemplo["tokens_in"] = "invalido"
            with caminho_exemplo.open("w", encoding="utf-8") as arquivo:
                json.dump(exemplo, arquivo, ensure_ascii=False)

            resultado = subprocess.run(
                [sys.executable, str(diretorio_copia / "validar-exemplos.py")],
                capture_output=True,
                check=False,
                encoding="utf-8",
            )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/consumo-tokens.json", resultado.stderr)
        self.assertIn("campo $.tokens_in", resultado.stderr)


if __name__ == "__main__":
    unittest.main()
