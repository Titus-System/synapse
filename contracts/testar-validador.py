from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any


DIRETORIO_CONTRATOS = Path(__file__).resolve().parent


def validar_com_alteracao(
    exemplo: str, alterar: Callable[[Any], None]
) -> subprocess.CompletedProcess[str]:
    """Roda o validador sobre uma cópia de contracts/ em que o exemplo foi alterado."""
    with tempfile.TemporaryDirectory() as diretorio_temporario:
        diretorio_copia = Path(diretorio_temporario) / "contracts"
        shutil.copytree(DIRETORIO_CONTRATOS, diretorio_copia)
        caminho_exemplo = diretorio_copia / "examples" / exemplo

        with caminho_exemplo.open(encoding="utf-8") as arquivo:
            conteudo = json.load(arquivo)
        alterar(conteudo)
        with caminho_exemplo.open("w", encoding="utf-8") as arquivo:
            json.dump(conteudo, arquivo, ensure_ascii=False)

        return subprocess.run(
            [sys.executable, str(diretorio_copia / "validar-exemplos.py")],
            capture_output=True,
            check=False,
            encoding="utf-8",
        )


class TestarValidador(unittest.TestCase):
    def test_rejeita_exemplo_com_campo_invalido(self) -> None:
        def alterar(exemplo: Any) -> None:
            exemplo["tokens_in"] = "invalido"

        resultado = validar_com_alteracao("domain/consumo-tokens.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/consumo-tokens.json", resultado.stderr)
        self.assertIn("campo $.tokens_in", resultado.stderr)


class TestarDiagnostico(unittest.TestCase):
    def test_rejeita_diagnostico_sem_causa(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["causa"]

        resultado = validar_com_alteracao("domain/resultado-diagnostico-timeout.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/resultado-diagnostico-timeout.json", resultado.stderr)
        self.assertIn("'causa' is a required property", resultado.stderr)

    def test_rejeita_falha_sem_traceback(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["falha"]["traceback"]

        resultado = validar_com_alteracao("domain/resultado-diagnostico-excecao.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.falha", resultado.stderr)
        self.assertIn("'traceback' is a required property", resultado.stderr)

    def test_rejeita_excecao_sem_falha(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["falha"]

        resultado = validar_com_alteracao("domain/resultado-diagnostico-excecao.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'falha' is a required property", resultado.stderr)

    def test_rejeita_falha_em_causa_sem_excecao_capturada(self) -> None:
        def alterar(diagnostico: Any) -> None:
            diagnostico["falha"] = {"tipo": "TimeoutError", "mensagem": "", "traceback": ""}

        resultado = validar_com_alteracao("domain/resultado-diagnostico-timeout.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("domain/resultado-diagnostico-timeout.json: campo $:", resultado.stderr)

    def test_rejeita_resultado_fora_do_schema_sem_problemas(self) -> None:
        def alterar(diagnostico: Any) -> None:
            del diagnostico["problemas"]

        resultado = validar_com_alteracao(
            "domain/resultado-diagnostico-fora-do-schema.json", alterar
        )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'problemas' is a required property", resultado.stderr)

    def test_rejeita_valor_na_palavra_chave(self) -> None:
        def alterar(diagnostico: Any) -> None:
            diagnostico["problemas"][0]["palavra_chave"] = "type: 'abc'"

        resultado = validar_com_alteracao(
            "domain/resultado-diagnostico-fora-do-schema.json", alterar
        )

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("campo $.problemas[0].palavra_chave", resultado.stderr)


class TestarJobEncerrado(unittest.TestCase):
    def test_rejeita_estado_que_nao_e_terminal(self) -> None:
        # Processamento, inviabilidade e espera pelo usuário são pausas retomáveis.
        nao_terminais = (
            "gerando_regra",
            "simulando",
            "simulacao_inviavel",
            "aguardando_decisao_usuario",
        )
        for status in nao_terminais:
            with self.subTest(status=status):

                def alterar(evento: Any, status: str = status) -> None:
                    evento["status"] = status

                resultado = validar_com_alteracao("events/job-encerrado.json", alterar)

                self.assertNotEqual(resultado.returncode, 0)
                self.assertIn("events/job-encerrado.json: campo $.status", resultado.stderr)

    def test_rejeita_encerramento_sem_identificador_estavel(self) -> None:
        def alterar(evento: Any) -> None:
            del evento["evento_id"]

        resultado = validar_com_alteracao("events/job-encerrado.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'evento_id' is a required property", resultado.stderr)

    def test_rejeita_encerramento_sem_o_instante_da_transicao(self) -> None:
        def alterar(evento: Any) -> None:
            del evento["encerrado_em"]

        resultado = validar_com_alteracao("events/job-encerrado-erro.json", alterar)

        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("'encerrado_em' is a required property", resultado.stderr)


if __name__ == "__main__":
    unittest.main()
