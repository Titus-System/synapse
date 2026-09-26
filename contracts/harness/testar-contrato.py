"""Testes do contrato do harness (T-034).

Cobrem: as bases chegam como cópia, uma execução processa mais de uma
competência (incluindo um mês em que a regra não tem efeito), o validador
aceita saída válida e recusa uma sem decomposição, e o exemplo passa no
validador.
"""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
from pandas.testing import assert_frame_equal

DIRETORIO_HARNESS = Path(__file__).resolve().parent
VALIDADOR = DIRETORIO_HARNESS / "validar-saida.py"
RAIZ_REPOSITORIO = DIRETORIO_HARNESS.parents[1]
DIRETORIO_BASELINES = RAIZ_REPOSITORIO / "worker" / "sandbox" / "data" / "domrock" / "baselines"
# Valores congelados antes da republicação: a mudança de formato não muda a apuração.
BASELINES_ESPERADOS = {
    "2025-08": (497, Decimal("363021.46")),
    "2025-09": (530, Decimal("424628.68")),
    "2025-10": (537, Decimal("698465.53")),
    "2025-11": (546, Decimal("508382.32")),
    "2025-12": (562, Decimal("1305396.25")),
}


def _ler_jsonl(caminho: Path) -> list[dict[str, Any]]:
    return [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines()]


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
        columns=["competencia_origem", "matricula", "tipo", "data_inicio", "data_fim"]
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


def _bases_multi_competencia() -> dict[str, pd.DataFrame]:
    """Três meses: set/out têm venda da marca/cargo alvo; nov não - cargo diferente."""
    vendas = pd.DataFrame(
        {
            "competencia": ["2025-09", "2025-10", "2025-11"],
            "cod_marca": [10, 10, 20],
            "cod_loja": [13, 13, 13],
            "matricula": ["MATRIC-1", "MATRIC-1", "MATRIC-1"],
            "vlr_venda": [10000.0, 8000.0, 500.0],
        }
    )
    return {
        "vendas": vendas,
        "rh": pd.DataFrame(),
        "comissoes": pd.DataFrame(),
        "eventos_rh": pd.DataFrame(),
    }


def _apuracao_base_multi_competencia() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "matricula": ["MATRIC-1", "MATRIC-1", "MATRIC-1"],
            "cod_loja": [13, 13, 13],
            "cod_marca": [10, 10, 10],
            # novembro é cargo 200: fora do alvo da regra (100), então sem efeito
            # mesmo tendo venda naquele mês.
            "cod_cargo": [100, 100, 200],
            "competencia": ["2025-09", "2025-10", "2025-11"],
            "comissao": [200.0, 150.0, 90.0],
        }
    )


class TestarBaselineReal(unittest.TestCase):
    def test_baseline_publicado_tem_exatamente_o_formato_de_apuracao_base(self) -> None:
        rh = {
            (linha["competencia"], linha["matricula"]): linha
            for linha in _ler_jsonl(DIRETORIO_BASELINES.parent / "rh.jsonl")
        }
        esperadas = {
            "matricula",
            "cod_loja",
            "cod_marca",
            "cod_cargo",
            "competencia",
            "comissao",
        }

        for competencia, (quantidade, total) in BASELINES_ESPERADOS.items():
            with self.subTest(competencia=competencia):
                linhas = _ler_jsonl(DIRETORIO_BASELINES / f"baseline-{competencia}.jsonl")
                self.assertEqual(len(linhas), quantidade)
                self.assertEqual(len({linha["matricula"] for linha in linhas}), quantidade)
                for linha in linhas:
                    self.assertEqual(set(linha), esperadas)
                    self.assertEqual(linha["competencia"], competencia)
                    self.assertIsInstance(linha["matricula"], str)
                    self.assertTrue(linha["matricula"])
                    pessoa = rh[(competencia, linha["matricula"])]
                    for campo in ("cod_loja", "cod_marca", "cod_cargo"):
                        self.assertIs(type(linha[campo]), int)
                        self.assertEqual(linha[campo], pessoa[campo])
                    self.assertIs(type(linha["comissao"]), float)
                    self.assertTrue(math.isfinite(linha["comissao"]))
                    self.assertGreaterEqual(linha["comissao"], 0.0)
                self.assertEqual(
                    sum((Decimal(str(linha["comissao"])) for linha in linhas), Decimal(0)),
                    total,
                )

    def test_exemplo_consumindo_baselines_reais_concatenados(self) -> None:
        competencias = list(BASELINES_ESPERADOS)
        # Lê diretamente os artefatos publicados, sem passar pelo adaptador do worker.
        # Assim um filtro/rename na carga não consegue esconder uma regressão da T-032.
        apuracao_base = pd.concat(
            [
                pd.DataFrame(_ler_jsonl(DIRETORIO_BASELINES / f"baseline-{c}.jsonl"))
                for c in competencias
            ],
            ignore_index=True,
        )
        bases = {
            nome: pd.DataFrame(_ler_jsonl(DIRETORIO_BASELINES.parent / f"{nome}.jsonl"))
            for nome in ("rh", "vendas", "comissoes", "eventos_rh")
        }
        for nome in ("rh", "vendas", "comissoes"):
            bases[nome] = bases[nome].loc[bases[nome]["competencia"].isin(competencias)].copy()

        self.assertFalse(apuracao_base.duplicated(["matricula", "competencia"]).any())
        saida = harness.chamar(regra.aplicar_regra, bases, apuracao_base, competencias)
        resultado = harness.montar_resultado(saida, apuracao_base, competencias, orcamento=0.0)

        self.assertEqual(len(saida["apuracao_simulada"]), len(apuracao_base))
        total_esperado = sum((total for _, total in BASELINES_ESPERADOS.values()), Decimal(0))
        self.assertAlmostEqual(resultado["totais"]["baseline"], float(total_esperado), places=6)
        self.assertNotEqual(resultado["totais"]["diferenca_abs"], 0.0)
        for dimensao in ("elemento", "loja", "marca", "cargo", "competencia"):
            self.assertAlmostEqual(
                sum(resultado["decomposicao"][dimensao].values()),
                resultado["totais"]["diferenca_abs"],
                places=6,
            )
        validador = _carregar_modulo(VALIDADOR, "validador_baseline_real")
        self.assertEqual(validador.validar_saida(resultado), [])


class TestarCopias(unittest.TestCase):
    def test_inplace_na_funcao_gerada_nao_afeta_o_harness(self) -> None:
        bases = _bases()
        originais = {nome: tabela.copy(deep=True) for nome, tabela in bases.items()}

        def regra_maliciosa(
            bases_recebidas: dict[str, pd.DataFrame],
            apuracao_base: pd.DataFrame,
            competencias: list[str],
        ) -> dict[str, pd.DataFrame]:
            bases_recebidas["vendas"]["vlr_venda"] = 0.0
            apuracao_base["comissao"] = -1.0
            return {
                "apuracao_simulada": apuracao_base,
                "contribuicoes": apuracao_base.head(0),
            }

        harness.chamar(regra_maliciosa, bases, _apuracao_base(), ["2025-11"])

        for nome, tabela in bases.items():
            assert_frame_equal(tabela, originais[nome])


class TestarMultiplasCompetencias(unittest.TestCase):
    """Uma execução processa o período inteiro - nunca um container por mês."""

    def test_uma_chamada_cobre_o_periodo_inteiro(self) -> None:
        bases = _bases_multi_competencia()
        apuracao_base = _apuracao_base_multi_competencia()
        competencias = ["2025-09", "2025-10", "2025-11"]

        saida = harness.chamar(regra.aplicar_regra, bases, apuracao_base, competencias)

        self.assertEqual(
            sorted(saida["apuracao_simulada"]["competencia"].unique()), competencias
        )

    def test_mes_sem_efeito_da_regra_aparece_com_zero_na_decomposicao(self) -> None:
        bases = _bases_multi_competencia()
        apuracao_base = _apuracao_base_multi_competencia()
        competencias = ["2025-09", "2025-10", "2025-11"]

        saida = harness.chamar(regra.aplicar_regra, bases, apuracao_base, competencias)
        resultado = harness.montar_resultado(saida, apuracao_base, competencias, orcamento=1000.0)

        # novembro foi simulado (o cargo não bate com o alvo da regra) - precisa
        # aparecer com 0, nunca ficar ausente do objeto.
        self.assertIn("2025-11", resultado["decomposicao"]["competencia"])
        self.assertEqual(resultado["decomposicao"]["competencia"]["2025-11"], 0.0)
        self.assertNotEqual(resultado["decomposicao"]["competencia"]["2025-09"], 0.0)
        self.assertNotEqual(resultado["decomposicao"]["competencia"]["2025-10"], 0.0)

    def test_soma_das_competencias_reconcilia_com_a_diferenca_total(self) -> None:
        bases = _bases_multi_competencia()
        apuracao_base = _apuracao_base_multi_competencia()
        competencias = ["2025-09", "2025-10", "2025-11"]

        saida = harness.chamar(regra.aplicar_regra, bases, apuracao_base, competencias)
        resultado = harness.montar_resultado(saida, apuracao_base, competencias, orcamento=1000.0)

        soma_por_competencia = sum(resultado["decomposicao"]["competencia"].values())
        self.assertAlmostEqual(soma_por_competencia, resultado["totais"]["diferenca_abs"])

    def test_saida_multi_competencia_e_aceita_pelo_validador(self) -> None:
        bases = _bases_multi_competencia()
        apuracao_base = _apuracao_base_multi_competencia()
        competencias = ["2025-09", "2025-10", "2025-11"]

        saida = harness.chamar(regra.aplicar_regra, bases, apuracao_base, competencias)
        resultado = harness.montar_resultado(saida, apuracao_base, competencias, orcamento=1000.0)

        arquivo = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        try:
            json.dump(resultado, arquivo, ensure_ascii=False)
            arquivo.close()
            processo = subprocess.run(
                [sys.executable, str(VALIDADOR), arquivo.name],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        finally:
            Path(arquivo.name).unlink(missing_ok=True)
        self.assertEqual(processo.returncode, 0, processo.stderr)


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
        saida = harness.chamar(regra.aplicar_regra, bases, apuracao_base, ["2025-11"])
        return harness.montar_resultado(saida, apuracao_base, ["2025-11"], orcamento=400.0)

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
