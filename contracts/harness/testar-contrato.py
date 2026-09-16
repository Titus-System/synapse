"""Testes do contrato do harness (T-034).

Cobrem: as bases chegam como cópia, o validador aceita saída válida e recusa
uma sem decomposição, e o exemplo passa no validador.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
from pandas.testing import assert_frame_equal

DIRETORIO_HARNESS = Path(__file__).resolve().parent
VALIDADOR = DIRETORIO_HARNESS / "validar-saida.py"


def _carregar_modulo(caminho: Path, nome: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(nome, caminho)
    if spec is None or spec.loader is None:
        raise ImportError(f"não foi possível carregar {caminho}")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


regra = _carregar_modulo(DIRETORIO_HARNESS / "exemplo" / "regra.py", "exemplo_regra")
harness = _carregar_modulo(DIRETORIO_HARNESS / "exemplo" / "harness.py", "exemplo_harness")


def _bases() -> dict[str, pd.DataFrame]:
    vendas = pd.DataFrame(
        {
            "competencia": ["2025-11", "2025-11"],
            "cod_marca": [10, 10],
            "cod_loja": [13, 58],
            "matricula": ["MATRIC-1", "MATRIC-2"],
            "vlr_venda": [10000.0, 5000.0],
        }
    )
    rh = pd.DataFrame(
        {
            "competencia": ["2025-11", "2025-11"],
            "matricula": ["MATRIC-1", "MATRIC-2"],
            "cod_marca": [10, 10],
            "cod_loja": [13, 58],
            "cod_cargo": [100, 100],
        }
    )
    comissoes = pd.DataFrame(
        {
            "competencia": ["2025-11"],
            "cod_marca": [10],
            "cod_cargo": [100],
            "percentual_comissao": [0.02],
        }
    )
    eventos_rh = pd.DataFrame(
        columns=["competencia", "matricula", "tipo", "data_inicio", "data_fim"]
    )
    return {"rh": rh, "vendas": vendas, "comissoes": comissoes, "eventos_rh": eventos_rh}


def _apuracao_base() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "matricula": ["MATRIC-1", "MATRIC-2"],
            "cod_loja": [13, 58],
            "cod_marca": [10, 10],
            "cod_cargo": [100, 100],
            "competencia": ["2025-11", "2025-11"],
            "comissao": [200.0, 100.0],
        }
    )


class TestarCopias(unittest.TestCase):
    def test_inplace_na_funcao_gerada_nao_afeta_o_harness(self) -> None:
        bases = _bases()
        originais = {nome: tabela.copy(deep=True) for nome, tabela in bases.items()}

        def regra_maliciosa(
            bases_recebidas: dict[str, pd.DataFrame],
            apuracao_base: pd.DataFrame,
            competencia: str,
        ) -> dict[str, pd.DataFrame]:
            bases_recebidas["vendas"]["vlr_venda"] = 0.0
            apuracao_base["comissao"] = -1.0
            return {
                "apuracao_simulada": apuracao_base,
                "contribuicoes": apuracao_base.head(0),
            }

        harness.chamar(regra_maliciosa, bases, _apuracao_base(), "2025-11")

        for nome, tabela in bases.items():
            assert_frame_equal(tabela, originais[nome])


class TestarValidador(unittest.TestCase):
    def _validar(self, saida: dict[str, Any]) -> subprocess.CompletedProcess[str]:
        arquivo = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        try:
            json.dump(saida, arquivo, ensure_ascii=False)
            arquivo.close()
            return subprocess.run(
                [sys.executable, str(VALIDADOR), arquivo.name],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        finally:
            Path(arquivo.name).unlink(missing_ok=True)

    def _saida_do_exemplo(self) -> dict[str, Any]:
        bases = _bases()
        apuracao_base = _apuracao_base()
        saida = harness.chamar(regra.aplicar_regra, bases, apuracao_base, "2025-11")
        return harness.montar_resultado(saida, apuracao_base, "2025-11", orcamento=400.0)

    def test_aceita_saida_valida(self) -> None:
        resultado = self._validar(self._saida_do_exemplo())
        self.assertEqual(resultado.returncode, 0, resultado.stderr)

    def test_recusa_saida_sem_decomposicao(self) -> None:
        saida = self._saida_do_exemplo()
        del saida["decomposicao"]
        resultado = self._validar(saida)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("decomposicao", resultado.stderr)

    def test_exemplo_e_aceito_pelo_validador(self) -> None:
        resultado = self._validar(self._saida_do_exemplo())
        self.assertEqual(resultado.returncode, 0, resultado.stderr)


if __name__ == "__main__":
    unittest.main()
