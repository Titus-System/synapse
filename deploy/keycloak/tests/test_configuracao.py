import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("configurar", ROOT / "configurar.py")
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class ConfiguracaoTests(unittest.TestCase):
    def test_admin_local_nao_encaminha_credenciais_ao_proxy(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"access_token":"token-sintetico"}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Um proxy inacessível torna o teste sensível a encaminhamento indevido.
            with patch.dict(
                os.environ, {"http_proxy": "http://127.0.0.1:1"}, clear=True
            ):
                admin = config.Admin(
                    {
                        "KEYCLOAK_ADMIN_URL": f"http://127.0.0.1:{server.server_port}",
                        "KEYCLOAK_ADMIN_PASSWORD": "senha-sintetica",
                    }
                )
            self.assertEqual("token-sintetico", admin.token)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def env(self):
        return {
            "KEYCLOAK_PUBLIC_URL": "http://localhost:8180",
            "KEYCLOAK_SMTP_HOST": "localhost",
            "KEYCLOAK_SMTP_FROM": "synapse@example.test",
            "KEYCLOAK_SMTP_USER": "test",
            "KEYCLOAK_SMTP_PASSWORD": "segredo-de-teste",
        }

    def test_smtp_tls_autenticado(self):
        result = config.smtp(self.env())
        self.assertEqual("true", result["starttls"])
        self.assertEqual("segredo-de-teste", result["password"])

    def test_smtp_exige_senha(self):
        env = self.env()
        del env["KEYCLOAK_SMTP_PASSWORD"]
        with self.assertRaisesRegex(ValueError, "PASSWORD"):
            config.smtp(env)

    def test_smtp_segredo_em_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secret"
            path.write_text("arquivo-secreto\n")
            result = config.smtp(
                self.env() | {"KEYCLOAK_SMTP_PASSWORD_FILE": str(path)}
            )
            self.assertEqual("arquivo-secreto", result["password"])

    def test_sem_auth_nao_envia_credenciais(self):
        result = config.smtp(self.env() | {"KEYCLOAK_SMTP_AUTH": "false"})
        self.assertNotIn("password", result)
        self.assertNotIn("user", result)

    def test_smtp_nao_aceita_tls_ambiguo(self):
        with self.assertRaises(ValueError):
            config.smtp(self.env() | {"KEYCLOAK_SMTP_SSL": "true"})

    def test_smtp_exige_excecao_local(self):
        with self.assertRaises(ValueError):
            config.smtp(self.env() | {"KEYCLOAK_SMTP_STARTTLS": "false"})
        env = self.env() | {
            "KEYCLOAK_SMTP_STARTTLS": "false",
            "KEYCLOAK_SMTP_ALLOW_INSECURE": "true",
        }
        self.assertEqual("false", config.smtp(env)["starttls"])
        with self.assertRaises(ValueError):
            config.smtp(env | {"KEYCLOAK_PUBLIC_URL": "https://auth.example.test"})

    def test_portas_invalidas(self):
        for port in ("0", "65536", "abc"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                config.smtp(self.env() | {"KEYCLOAK_SMTP_PORT": port})

    def test_origem_sem_open_redirect(self):
        for url in (
            "http://evil.test",
            "https://app.test/*",
            "https://app.test/#x",
            "https://a:b@app.test",
            "https://app.test/callback",
            "https://app.test/?x=1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                config.origem(url)
        self.assertEqual("https://app.test", config.origem("https://app.test/"))

    def test_env_nao_executa_shell_e_ambiente_prevalece(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text('A="$(comando)"\nB=arquivo\n# comentario\n')
            with patch.dict(os.environ, {"B": "ambiente"}, clear=True):
                result = config.ambiente(path)
            self.assertEqual({"A": "$(comando)", "B": "ambiente"}, result)

    def test_modelo_sem_smtp_secreto_ou_papel_privilegiado(self):
        realm = json.loads((ROOT / "realm-synapse.json").read_text())
        self.assertNotIn("smtpServer", realm)
        self.assertEqual(["profissional-rh"], realm["groups"][0]["realmRoles"])
        self.assertTrue(realm["verifyEmail"])
        self.assertFalse(realm["clients"][0]["directAccessGrantsEnabled"])


if __name__ == "__main__":
    unittest.main()
