"""Regressões do isolamento e da configuração persistente do ambiente local."""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ARQUIVO = Path(__file__).resolve().parents[1] / "local/iniciar.py"
spec = importlib.util.spec_from_file_location("iniciar_local", ARQUIVO)
local = importlib.util.module_from_spec(spec)
spec.loader.exec_module(local)


class AmbienteLocalTests(unittest.TestCase):
    def test_reinicio_preserva_senhas_e_nao_cria_env_de_producao(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / ".env"
            with patch.object(local, "ENV_FILE", arquivo):
                primeiro = local.ambiente_local()
                original = arquivo.read_bytes()
                self.assertEqual(primeiro, local.ambiente_local())
                self.assertEqual(original, arquivo.read_bytes())
                self.assertEqual(3, len(set(primeiro.values())))
                self.assertTrue(all(len(v) >= 32 for v in primeiro.values()))
                self.assertEqual([arquivo], list(Path(pasta).iterdir()))

    def test_env_incompleto_nao_e_sobrescrito(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / ".env"
            original = b"E11_ADMIN_PASSWORD=fixture-local\n"
            arquivo.write_bytes(original)
            with patch.object(local, "ENV_FILE", arquivo):
                with self.assertRaisesRegex(RuntimeError, "incompleto"):
                    local.ambiente_local()
                self.assertEqual(original, arquivo.read_bytes())

    def test_exportacoes_nao_trocam_projeto_nem_senhas_do_volume(self):
        herdado = dict.fromkeys(local.CHAVES, "fixture-exportada") | {
            "COMPOSE_FILE": "producao.yml",
            "COMPOSE_PROJECT_NAME": "producao",
            "COMPOSE_PROFILES": "outros",
            "PATH": "preservar-path",
            "HTTPS_PROXY": "http://proxy.example.test",
        }
        with patch.dict(os.environ, herdado, clear=True):
            self.assertEqual(
                {"PATH": "preservar-path", "HTTPS_PROXY": "http://proxy.example.test"},
                local.env_docker(),
            )

    def test_encerramento_dos_testes_nao_remove_ambiente_manual(self):
        testes = local.compose("down", testes=True)
        manual = local.compose("down")
        self.assertIn("synapse-e11-test", testes)
        self.assertNotIn("synapse-e11-local", testes)
        self.assertNotIn("--env-file", testes)
        self.assertIn("synapse-e11-local", manual)
        self.assertIn(str(local.ENV_FILE), manual)
        self.assertNotIn("-v", manual)
