"""Integração real. Cria e remove apenas realms e11-test-<uuid> em servidor local."""

import base64
import hashlib
import importlib.util
import json
import os
import secrets
import threading
import time
import unittest
import uuid
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("configurar", ROOT / "configurar.py")
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
URL = os.environ.get("KEYCLOAK_E2E_URL", "")
PASSWORD = "Senha-local-teste-123!"
NEW_PASSWORD = "Outra-senha-teste-456!"


class SessaoLocal(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False

    def send(self, request, **kwargs):
        try:
            response = super().send(request, **kwargs)
        except (requests.Timeout, requests.ConnectionError):
            raise AssertionError(
                "O serviço local não respondeu no prazo. Confira os containers e "
                "a etapa exibida acima. O comando local/iniciar.py testar usa SMTP "
                "dentro do Docker e evita dependência do firewall do Windows."
            ) from None
        # Browsers aceitam cookies Secure em localhost (origem confiável).
        # requests não implementa essa exceção. Ela vale só para o servidor local de teste.
        if urlsplit(response.url).hostname in ("localhost", "127.0.0.1"):
            for cookie in self.cookies:
                cookie.secure = False
        return response


class CaixaPostal:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(
            BytesParser(policy=policy.default).parsebytes(envelope.content)
        )
        return "250 OK"

    def clear(self):
        self.messages.clear()

    def link(self, recipient):
        messages = [m for m in self.messages if recipient in str(m["To"])]
        if not messages:
            raise AssertionError("O SMTP local não recebeu a mensagem esperada.")
        html = messages[-1].get_body(preferencelist=("html",)).get_content()
        return BeautifulSoup(html, "html.parser").select_one("a[href]")["href"]


class CaixaMailpit(CaixaPostal):
    """Lê SMTP capturado no Docker sem abrir um servidor no host Windows."""

    def __init__(self, url):
        self.url = config.origem(url)
        if urlsplit(self.url).hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("Use somente uma caixa Mailpit local para estes testes.")
        self.session = SessaoLocal()
        self.anteriores = set()
        self.clear()

    def listar(self):
        response = self.session.get(self.url + "/api/v1/messages?limit=100", timeout=10)
        response.raise_for_status()
        return response.json()["messages"]

    def clear(self):
        # Preserva mensagens anteriores para diagnóstico, sem misturá-las ao caso.
        self.anteriores = {m["ID"] for m in self.listar()}

    @property
    def messages(self):
        mensagens = []
        for mensagem in reversed(self.listar()):
            if mensagem["ID"] not in self.anteriores:
                response = self.session.get(
                    self.url + "/api/v1/message/" + mensagem["ID"] + "/raw",
                    timeout=10,
                )
                response.raise_for_status()
                mensagens.append(
                    BytesParser(policy=policy.default).parsebytes(response.content)
                )
        return mensagens


@unittest.skipUnless(URL, "Defina KEYCLOAK_E2E_URL para testar um Keycloak local.")
class FluxosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("Use somente um Keycloak de teste local.")
        mailpit = os.environ.get("KEYCLOAK_E2E_MAILPIT_URL", "")
        cls.smtp = None
        if mailpit:
            cls.mail = CaixaMailpit(mailpit)
        else:
            from aiosmtpd.controller import Controller

            cls.mail = CaixaPostal()
            # Modo nativo opcional: hostname vazio evita WinError 10049.
            cls.smtp = Controller(cls.mail, hostname="", port=1025)
            cls.smtp.start()
        cls.env = dict(os.environ) | {
            "KEYCLOAK_ADMIN_URL": URL,
            "KEYCLOAK_PUBLIC_URL": URL,
            "SYNAPSE_FRONTEND_URL": "http://localhost:5173",
            "KEYCLOAK_SMTP_HOST": os.environ.get(
                "KEYCLOAK_E2E_SMTP_HOST", "mailpit" if mailpit else "127.0.0.1"
            ),
            "KEYCLOAK_SMTP_PORT": "1025",
            "KEYCLOAK_SMTP_FROM": "synapse@example.test",
            "KEYCLOAK_SMTP_AUTH": "false",
            "KEYCLOAK_SMTP_STARTTLS": "false",
            "KEYCLOAK_SMTP_SSL": "false",
            "KEYCLOAK_SMTP_ALLOW_INSECURE": "true",
        }

    @classmethod
    def tearDownClass(cls):
        if cls.smtp:
            cls.smtp.stop()

    def setUp(self):
        self.inicio = time.monotonic()
        self.fim = threading.Event()
        self.etapa("conectando à Admin API")
        self.observador = threading.Thread(target=self.acompanhar, daemon=True)
        self.observador.start()
        self.addCleanup(self.encerrar_progresso)
        self.realm = "e11-test-" + uuid.uuid4().hex
        self.admin = config.Admin(self.env, self.realm)
        self.etapa("criando realm descartável")
        self.template = json.loads((ROOT / "realm-synapse.json").read_text())
        self.template["realm"] = self.realm
        self.admin.call("POST", "/admin/realms", self.template)
        self.addCleanup(lambda: self.admin.call("DELETE"))
        self.etapa("aplicando configuração do realm")
        config.aplicar(self.admin, self.env)
        self.base = URL + "/realms/" + self.realm
        self.session = SessaoLocal()
        self.verifier = secrets.token_urlsafe(48)
        self.mail.clear()
        self.etapa("executando cenário")

    def etapa(self, descricao):
        self.etapa_atual = descricao
        print(
            f"\n  [E11 +{time.monotonic() - self.inicio:.0f}s] {descricao}", flush=True
        )

    def acompanhar(self):
        while not self.fim.wait(10):
            print(
                f"\n  [E11 +{time.monotonic() - self.inicio:.0f}s] aguardando: {self.etapa_atual}",
                flush=True,
            )

    def encerrar_progresso(self):
        self.fim.set()
        self.observador.join(timeout=1)
        print(
            f"  [E11] caso encerrado em {time.monotonic() - self.inicio:.1f}s",
            flush=True,
        )

    def auth(self, session=None):
        session = session or self.session
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return session.get(
            self.base + "/protocol/openid-connect/auth",
            params={
                "client_id": "synapse-frontend",
                "redirect_uri": "http://localhost:5173/",
                "response_type": "code",
                "scope": "openid profile email",
                "state": "test-state",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            timeout=30,
        )

    def html(self, response):
        self.assertEqual(200, response.status_code)
        self.assertNotIn("Internal Server Error", response.text)
        return BeautifulSoup(response.text, "html.parser")

    def submit(self, page, data, selector="form", session=None):
        form = self.html(page).select_one(selector)
        self.assertIsNotNone(form, "O formulário nativo não foi renderizado.")
        values = {
            i["name"]: i.get("value", "")
            for i in form.select("input[type=hidden][name]")
        }
        values.update(data)
        return (session or self.session).post(
            urljoin(page.url, form["action"]),
            data=values,
            allow_redirects=False,
            timeout=30,
        )

    def follow(self, response, session=None):
        session = session or self.session
        for _ in range(8):
            if not response.is_redirect or response.headers["Location"].startswith(
                "http://localhost:5173/"
            ):
                return response
            response = session.get(
                urljoin(response.url, response.headers["Location"]),
                allow_redirects=False,
                timeout=30,
            )
        self.fail("Redirecionamentos em excesso.")

    def register_page(self):
        login = self.html(self.auth())
        self.assertIsNotNone(login.select_one('a[href*="reset-credentials"]'))
        return self.session.get(
            urljoin(URL, login.select_one("#synapse-register")["href"]), timeout=30
        )

    def register(self, email, password=PASSWORD, confirm=None, name="Pessoa de Teste"):
        self.etapa("enviando cadastro e aguardando envio do e-mail pelo Keycloak")
        return self.follow(
            self.submit(
                self.register_page(),
                {
                    "firstName": name,
                    "email": email,
                    "password": password,
                    "password-confirm": password if confirm is None else confirm,
                    # Tentativas de elevar privilégios devem ser ignoradas pelo perfil nativo.
                    "user.attributes.roles": "auditor",
                    "realmRoles": "auditor",
                },
            )
        )

    def users(self, email):
        return self.admin.call(
            "GET", "/users?" + urlencode({"email": email, "exact": "true"})
        )

    def roles(self, user_id):
        return {
            r["name"]
            for r in self.admin.call(
                "GET", f"/users/{user_id}/role-mappings/realm/composite"
            )
        }

    def token(self, response):
        self.etapa("validando retorno OIDC e token")
        if not response.is_redirect:
            self.fail(self.html(response).get_text(" ", strip=True)[-800:])
        params = parse_qs(urlsplit(response.headers["Location"]).query)
        self.assertEqual(["test-state"], params["state"])
        result = self.session.post(
            self.base + "/protocol/openid-connect/token",
            data={
                "client_id": "synapse-frontend",
                "grant_type": "authorization_code",
                "code": params["code"][0],
                "redirect_uri": "http://localhost:5173/",
                "code_verifier": self.verifier,
            },
            timeout=30,
        )
        self.assertEqual(200, result.status_code)
        self.tokens = result.json()
        token = self.tokens["access_token"]
        return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))

    def login(self, email, password, session=None):
        session = session or self.session
        return self.follow(
            self.submit(
                self.auth(session),
                {"username": email, "password": password},
                session=session,
            ),
            session,
        )

    def reset_request(self, email):
        self.etapa("solicitando recuperação e aguardando SMTP")
        session = SessaoLocal()
        page = self.html(self.auth(session))
        reset = session.get(
            urljoin(URL, page.select_one('a[href*="reset-credentials"]')["href"]),
            timeout=30,
        )
        response = self.follow(
            self.submit(reset, {"username": email}, session=session), session
        )
        return session, response

    def create_verified(self, email, role="profissional-rh"):
        self.admin.call(
            "POST",
            "/users",
            {
                "username": email,
                "email": email,
                "firstName": "Pessoa",
                "enabled": True,
                "emailVerified": True,
                "credentials": [
                    {"type": "password", "value": PASSWORD, "temporary": False}
                ],
            },
        )
        return self.users(email)[0]["id"]

    def test_cadastro_verificacao_token_pkce_e_duplicado(self):
        email = "nova@example.test"
        result = self.register(email)
        self.assertIn("Verifique seu e-mail", result.text)
        user = self.users(email)[0]
        self.assertFalse(user["emailVerified"])
        self.assertEqual(
            {"profissional-rh"},
            self.roles(user["id"]) & {"profissional-rh", "auditor", "admin"},
        )
        verified = self.follow(
            self.session.get(self.mail.link(email), allow_redirects=False, timeout=30)
        )
        claims = self.token(verified)
        self.assertEqual(user["id"], claims["sub"])
        self.assertTrue(claims["email_verified"])
        self.assertEqual("Pessoa de Teste", claims["name"])
        # Nova sessão evita o SSO ao exercitar a tentativa duplicada.
        self.session = SessaoLocal()
        duplicate = self.register(email)
        self.assertEqual(200, duplicate.status_code)
        self.assertEqual(1, len(self.users(email)))
        self.assertNotIn("Internal Server Error", duplicate.text)

    def test_erros_de_cadastro_nao_criam_usuario(self):
        for email, password, confirm, name, message in [
            ("invalido", PASSWORD, PASSWORD, "Pessoa", "e-mail"),
            (
                "vazio@example.test",
                PASSWORD,
                PASSWORD,
                "",
                "Por favor, informe este campo.",
            ),
            ("curta@example.test", "abc", "abc", "Pessoa", "12"),
            ("diferente@example.test", PASSWORD, NEW_PASSWORD, "Pessoa", "coincidem"),
        ]:
            with self.subTest(case=email):
                response = self.register(email, password, confirm, name)
                self.assertIn(message, response.text)
                self.assertEqual([], self.users(email))

    def test_recuperacao_generica_senha_antiga_reuso_e_identidade(self):
        email = "existente@example.test"
        user_id = self.create_verified(email)
        before = self.token(self.login(email, PASSWORD))
        known_session, known = self.reset_request(email)
        link = self.mail.link(email)
        _, unknown = self.reset_request("inexistente@example.test")
        known_message = (
            self.html(known).select_one(".synapse-message").get_text(strip=True)
        )
        self.assertEqual(
            known_message,
            self.html(unknown).select_one(".synapse-message").get_text(strip=True),
        )
        self.assertEqual(1, len(self.mail.messages))
        reset = known_session.get(link, timeout=30)
        mismatch = self.follow(
            self.submit(
                reset,
                {"password-new": NEW_PASSWORD, "password-confirm": PASSWORD},
                session=known_session,
            ),
            known_session,
        )
        self.assertIn("coincidem", mismatch.text)
        updated = self.follow(
            self.submit(
                mismatch,
                {"password-new": NEW_PASSWORD, "password-confirm": NEW_PASSWORD},
                session=known_session,
            ),
            known_session,
        )
        self.assertFalse(
            updated.is_redirect,
            "A recuperação deve retornar ao login, sem autenticar automaticamente.",
        )
        confirmation = self.html(updated).select_one("#kc-info-message")
        self.assertIsNotNone(confirmation)
        self.assertEqual("http://localhost:5173/", confirmation.select_one("a")["href"])
        self.assertIn("Voltar ao login", confirmation.get_text())
        # A rota protegida do frontend inicia uma nova autenticação OIDC.
        self.assertIsNotNone(
            self.html(self.auth(known_session)).select_one("#kc-form-login")
        )
        self.session = SessaoLocal()
        rejected = self.login(email, PASSWORD)
        self.assertIsNotNone(self.html(rejected).select_one("#kc-form-login"))
        after = self.token(self.login(email, NEW_PASSWORD))
        self.assertEqual(before["sub"], after["sub"])
        self.assertEqual(user_id, after["sub"])
        self.assertEqual(
            before["realm_access"]["roles"], after["realm_access"]["roles"]
        )
        replay_session = SessaoLocal()
        replay = self.follow(
            replay_session.get(link, allow_redirects=False, timeout=30), replay_session
        )
        self.assertNotIn('id="kc-passwd-update-form"', replay.text)
        self.assertTrue(
            "solicitar" in replay.text.lower() or "expir" in replay.text.lower()
        )
        self.assertEqual(1, len(self.users(email)))

    def test_link_expirado_e_adulterado(self):
        email = "expirado@example.test"
        self.create_verified(email)
        realm = self.admin.call("GET")
        self.admin.call(
            "PUT",
            body={
                "attributes": realm.get("attributes", {})
                | {"actionTokenGeneratedByUserLifespan.reset-credentials": "1"}
            },
        )
        session, _ = self.reset_request(email)
        link = self.mail.link(email)
        time.sleep(2)
        expired = self.follow(
            session.get(link, allow_redirects=False, timeout=30), session
        )
        self.assertNotIn('id="kc-passwd-update-form"', expired.text)
        self.assertIn("expir", expired.text.lower())
        parsed = urlsplit(link)
        params = parse_qs(parsed.query)
        params["key"] = ["invalid-token"]
        invalid = session.get(
            parsed._replace(query=urlencode(params, doseq=True)).geturl(), timeout=30
        )
        self.assertNotIn('id="kc-passwd-update-form"', invalid.text)
        self.assertIn("solicitar", invalid.text.lower())

    def test_reaplicacao_preserva_usuario_e_auditor_existente(self):
        # Recria somente este realm descartável com a estrutura anterior ao E11.
        self.admin.call("DELETE")
        legacy = {
            k: self.template[k]
            for k in ("realm", "enabled", "displayName", "roles", "clients")
        }
        self.admin.call("POST", "/admin/realms", legacy)
        email = "auditor@example.test"
        user_id = self.create_verified(email)
        for group in self.admin.call("GET", f"/users/{user_id}/groups"):
            self.admin.call("DELETE", f"/users/{user_id}/groups/{group['id']}")
        role = self.admin.call("GET", "/roles/auditor")
        self.admin.call("POST", f"/users/{user_id}/role-mappings/realm", [role])
        before = self.roles(user_id)
        config.aplicar(self.admin, self.env)
        config.aplicar(self.admin, self.env)
        self.assertEqual(before, self.roles(user_id))
        self.assertNotIn("profissional-rh", self.roles(user_id))
        self.assertEqual(user_id, self.token(self.login(email, PASSWORD))["sub"])
        self.assertEqual(1, len(self.admin.call("GET", "/default-groups")))

    def test_seed_cria_auditor_sem_papel_operacional(self):
        seed_spec = importlib.util.spec_from_file_location(
            "synapse_seed", ROOT.parent / "scripts/seed.py"
        )
        seed = importlib.util.module_from_spec(seed_spec)
        import sys

        sys.modules[seed_spec.name] = seed
        seed_spec.loader.exec_module(seed)
        admin = seed.KeycloakAdmin(
            URL,
            self.realm,
            self.env.get("KEYCLOAK_ADMIN_USERNAME", "admin"),
            self.env["KEYCLOAK_ADMIN_PASSWORD"],
        )
        for user in seed.USUARIOS:
            user_id = admin.provisionar_usuario(user, PASSWORD)
            self.assertEqual(
                {user["papel_keycloak"]},
                self.roles(user_id) & {"profissional-rh", "auditor"},
            )
            self.assertEqual(user_id, admin.provisionar_usuario(user, PASSWORD))

    def test_renovacao_e_logout_preservam_contrato_oidc(self):
        email = "sessao@example.test"
        self.create_verified(email)
        claims = self.token(self.login(email, PASSWORD))
        refresh = self.session.post(
            self.base + "/protocol/openid-connect/token",
            data={
                "client_id": "synapse-frontend",
                "grant_type": "refresh_token",
                "refresh_token": self.tokens["refresh_token"],
            },
            timeout=30,
        )
        self.assertEqual(200, refresh.status_code)
        renewed = json.loads(
            base64.urlsafe_b64decode(
                refresh.json()["access_token"].split(".")[1] + "==="
            )
        )
        self.assertEqual(claims["sub"], renewed["sub"])
        logout = self.follow(
            self.session.get(
                self.base + "/protocol/openid-connect/logout",
                params={
                    "id_token_hint": refresh.json()["id_token"],
                    "post_logout_redirect_uri": "http://localhost:5173/",
                },
                allow_redirects=False,
                timeout=30,
            )
        )
        self.assertTrue(logout.is_redirect)
        self.assertEqual("http://localhost:5173/", logout.headers["Location"])
        self.assertIsNotNone(self.html(self.auth()).select_one("#kc-form-login"))

    def test_eventos_e_metricas_sem_segredos(self):
        email = "eventos@example.test"
        self.create_verified(email)
        self.login(email, "senha-incorreta")
        self.reset_request(email)
        events = self.admin.call("GET", "/events")
        types = {e["type"] for e in events}
        self.assertIn("LOGIN_ERROR", types)
        self.assertIn("SEND_RESET_PASSWORD", types)
        serialized = json.dumps(events)
        self.assertNotIn(PASSWORD, serialized)
        self.assertNotIn("senha-incorreta", serialized)
        self.assertNotIn("key=", serialized)
        metrics_url = os.environ.get("KEYCLOAK_E2E_METRICS_URL")
        if metrics_url:
            session = SessaoLocal()
            metrics = session.get(metrics_url, timeout=20)
            self.assertEqual(200, metrics.status_code)
            self.assertIn(self.realm, metrics.text)
            self.assertIn("keycloak_user_events_total", metrics.text)

    @unittest.skipUnless(
        os.environ.get("SYNAPSE_TEST_CHROMIUM"),
        "Validação visual opcional requer Chromium e Playwright.",
    )
    def test_tema_no_navegador_desktop_e_mobile(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ["SYNAPSE_TEST_CHROMIUM"],
                headless=True,
                args=["--no-sandbox"],
            )
            for width, height in ((1440, 1000), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on(
                    "pageerror",
                    lambda error, collected=errors: collected.append(str(error)),
                )
                page.goto(self.auth().url)
                page.locator("#synapse-register").click()
                page.locator("#firstName").fill("Pessoa de Teste")
                page.locator("#email").fill("visual@example.test")
                page.locator("#password").fill(PASSWORD)
                page.locator("#password-confirm").fill(PASSWORD)
                page.locator("#password-show-password").click()
                self.assertEqual(
                    "text", page.locator("#password").get_attribute("type")
                )
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width
                )
                folder = os.environ.get("KEYCLOAK_SCREENSHOT_DIR")
                if folder:
                    Path(folder).mkdir(parents=True, exist_ok=True)
                    page.screenshot(
                        path=str(Path(folder) / f"cadastro-{width}.png"), full_page=True
                    )
                self.assertEqual([], errors)
                page.get_by_text("Voltar ao login", exact=True).click()
                page.get_by_text("Esqueceu a senha?", exact=True).click()
                self.assertTrue(page.locator("#kc-reset-password-form").is_visible())
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width
                )
                if folder:
                    page.screenshot(
                        path=str(Path(folder) / f"recuperacao-{width}.png"),
                        full_page=True,
                    )
                page.close()
            browser.close()


if __name__ == "__main__":
    unittest.main()
