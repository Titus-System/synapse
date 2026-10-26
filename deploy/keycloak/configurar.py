"""Aplica o E11 pela Admin API, sem reimportar nem recriar usuários do realm."""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib import error, parse, request

ROOT = Path(__file__).resolve().parent
GROUP = "synapse-autocadastro"


def ambiente(arquivo):
    valores = {}
    if arquivo:
        for linha in Path(arquivo).read_text(encoding="utf-8-sig").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            chave, separador, valor = linha.partition("=")
            if not separador:
                raise ValueError("O arquivo de ambiente deve conter CHAVE=valor.")
            valor = valor.strip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                valor = valor[1:-1]
            valores[chave.strip()] = valor
    return valores | dict(os.environ)


def obrigatorio(env, chave):
    valor = env.get(chave, "")
    if not valor.strip():
        raise ValueError(f"Defina {chave} no ambiente.")
    return valor


def booleano(env, chave, padrao):
    valor = env.get(chave, padrao).lower()
    if valor not in ("true", "false"):
        raise ValueError(f"{chave} deve ser true ou false.")
    return valor


def origem(valor):
    url = parse.urlsplit(valor)
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
        or "*" in valor
    ):
        raise ValueError(
            "Configure uma origem HTTP(S) sem caminho, credenciais ou curingas."
        )
    if url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            "URLs públicas devem usar HTTPS. HTTP é permitido somente no loopback."
        )
    return valor.rstrip("/")


def smtp(env):
    senha = env.get("KEYCLOAK_SMTP_PASSWORD", "")
    arquivo = env.get("KEYCLOAK_SMTP_PASSWORD_FILE", "")
    if arquivo:
        senha = Path(arquivo).read_text(encoding="utf-8").rstrip("\r\n")
    config = {
        "host": obrigatorio(env, "KEYCLOAK_SMTP_HOST"),
        "port": env.get("KEYCLOAK_SMTP_PORT", "587"),
        "from": obrigatorio(env, "KEYCLOAK_SMTP_FROM"),
        "fromDisplayName": env.get("KEYCLOAK_SMTP_FROM_DISPLAY_NAME", "Synapse"),
        "auth": booleano(env, "KEYCLOAK_SMTP_AUTH", "true"),
        "starttls": booleano(env, "KEYCLOAK_SMTP_STARTTLS", "true"),
        "ssl": booleano(env, "KEYCLOAK_SMTP_SSL", "false"),
    }
    if not config["port"].isdigit() or not 1 <= int(config["port"]) <= 65535:
        raise ValueError("KEYCLOAK_SMTP_PORT inválida.")
    if config["starttls"] == config["ssl"] == "true":
        raise ValueError("Use STARTTLS ou SSL implícito, nunca ambos.")
    if config["starttls"] == config["ssl"] == "false":
        if booleano(env, "KEYCLOAK_SMTP_ALLOW_INSECURE", "false") != "true":
            raise ValueError(
                "SMTP exige TLS. A exceção deve ser explícita e somente para teste local."
            )
        if parse.urlsplit(
            origem(obrigatorio(env, "KEYCLOAK_PUBLIC_URL"))
        ).hostname not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("SMTP sem TLS é permitido somente em um Keycloak local.")
    if config["auth"] == "true":
        config["user"] = obrigatorio(env, "KEYCLOAK_SMTP_USER")
        if not senha:
            raise ValueError(
                "Defina KEYCLOAK_SMTP_PASSWORD ou KEYCLOAK_SMTP_PASSWORD_FILE."
            )
        config["password"] = senha
    if env.get("KEYCLOAK_SMTP_REPLY_TO"):
        config["replyTo"] = env["KEYCLOAK_SMTP_REPLY_TO"]
    return config


class Admin:
    def __init__(self, env, realm="synapse"):
        self.url = origem(
            env.get("KEYCLOAK_ADMIN_URL") or obrigatorio(env, "KEYCLOAK_PUBLIC_URL")
        )
        # No Windows, urllib também lê o proxy do sistema. A Admin API local
        # deve ser acessada diretamente, sem encaminhar credenciais ao proxy.
        self.opener = (
            request.build_opener(request.ProxyHandler({}))
            if parse.urlsplit(self.url).hostname in ("localhost", "127.0.0.1", "::1")
            else request.build_opener()
        )
        self.token = None
        self.base = "/admin/realms/" + parse.quote(realm, safe="")
        self.login_form = {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": env.get("KEYCLOAK_ADMIN_USERNAME", "admin"),
            "password": obrigatorio(env, "KEYCLOAK_ADMIN_PASSWORD"),
        }
        resposta = self.call(
            "POST", "/realms/master/protocol/openid-connect/token", form=self.login_form
        )
        self.token = resposta["access_token"]

    def call(self, method, path="", body=None, form=None, retry=True):
        headers = {"Accept": "application/json"}
        data = None
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if form is not None:
            data = parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        prefix = "" if path.startswith(("/realms/", "/admin/")) else self.base
        try:
            with self.opener.open(
                request.Request(
                    self.url + prefix + path, data=data, headers=headers, method=method
                ),
                timeout=30,
            ) as response:
                content = response.read()
                return json.loads(content) if content else None
        except error.HTTPError as exc:
            if (
                exc.code == 401
                and self.token
                and retry
                and not path.startswith("/realms/")
            ):
                self.token = None
                resposta = self.call(
                    "POST",
                    "/realms/master/protocol/openid-connect/token",
                    form=self.login_form,
                )
                self.token = resposta["access_token"]
                return self.call(method, path, body, form, retry=False)
            # Respostas e payloads podem conter credenciais e tokens.
            raise RuntimeError(
                f"Keycloak recusou uma operação administrativa: HTTP {exc.code}."
            ) from None
        except (error.URLError, TimeoutError):
            raise RuntimeError("Não foi possível conectar ao Keycloak.") from None


def configurar_fluxo(admin, source, alias, provider, config):
    flows = admin.call("GET", "/authentication/flows")
    if not any(flow["alias"] == alias for flow in flows):
        admin.call(
            "POST",
            f"/authentication/flows/{parse.quote(source, safe='')}/copy",
            {"newName": alias},
        )
    path = f"/authentication/flows/{alias}/executions"
    executions = admin.call("GET", path)
    required = (
        ("registration-user-creation", "registration-password-action")
        if source == "registration"
        else (
            "reset-credentials-choose-user",
            "reset-credential-email",
            "reset-password",
        )
    )
    for expected in required:
        steps = [e for e in executions if e.get("providerId") == expected]
        if len(steps) != 1 or steps[0]["requirement"] != "REQUIRED":
            raise ValueError(
                f"Revise o fluxo {alias}: a etapa {expected} deve ser única e REQUIRED."
            )
    matches = [e for e in executions if e.get("providerId") == provider]
    if len(matches) != 1 or matches[0]["requirement"] != "REQUIRED":
        raise ValueError(
            f"Revise o fluxo {alias}: a etapa nativa {provider} deve ser única e REQUIRED."
        )
    execution = matches[0]
    if execution.get("authenticationConfig"):
        config_path = "/authentication/config/" + execution["authenticationConfig"]
        current = admin.call("GET", config_path)
        current["config"] = current.get("config", {}) | config
        admin.call("PUT", config_path, current)
    else:
        admin.call(
            "POST",
            f"/authentication/executions/{execution['id']}/config",
            {"alias": alias + "-config", "config": config},
        )


def validar_papeis_padrao(admin, realm):
    default = realm.get("defaultRole")
    account = admin.call("GET", "/clients?clientId=account")
    account_id = account[0]["id"] if account else None
    if default:
        pending = admin.call("GET", f"/roles-by-id/{default['id']}/composites")
        seen = set()
        while pending:
            role = pending.pop()
            if role["id"] in seen:
                continue
            seen.add(role["id"])
            if role.get("composite"):
                pending.extend(
                    admin.call("GET", f"/roles-by-id/{role['id']}/composites")
                )
            elif not (
                (role.get("clientRole") and role.get("containerId") == account_id)
                or (
                    not role.get("clientRole")
                    and role["name"] in ("offline_access", "uma_authorization")
                )
            ):
                raise ValueError(
                    "O papel padrão contém permissões adicionais. Revise-o antes de habilitar o cadastro."
                )
    for group in admin.call("GET", "/default-groups"):
        roles = admin.call(
            "GET", f"/groups/{group['id']}/role-mappings/realm/composite"
        )
        if any(r["name"] != "profissional-rh" for r in roles):
            raise ValueError(
                "Há um grupo padrão com permissões adicionais. Revise os grupos padrão."
            )
        mappings = admin.call("GET", f"/groups/{group['id']}/role-mappings")
        if mappings.get("clientMappings"):
            raise ValueError(
                "Há um grupo padrão com papéis de cliente. Revise antes do cadastro."
            )


def aplicar(admin, env):
    template = json.loads((ROOT / "realm-synapse.json").read_text(encoding="utf-8"))
    mail = smtp(env)
    frontend = origem(obrigatorio(env, "SYNAPSE_FRONTEND_URL"))
    public = origem(obrigatorio(env, "KEYCLOAK_PUBLIC_URL"))
    realm = admin.call("GET")
    for key, allowed in (
        ("registrationFlow", ("registration", "synapse-registration")),
        ("resetCredentialsFlow", ("reset credentials", "synapse-reset-credentials")),
    ):
        if realm.get(key) not in allowed:
            raise ValueError(
                f"{key} já foi personalizado. Revise-o antes de aplicar o E11."
            )
    validar_papeis_padrao(admin, realm)
    clients = admin.call("GET", "/clients?clientId=synapse-frontend")
    if len(clients) != 1:
        raise ValueError("O cliente synapse-frontend deve existir uma única vez.")
    # Desabilita os formulários até concluir todas as configurações dependentes.
    admin.call(
        "PUT", body={"registrationAllowed": False, "resetPasswordAllowed": False}
    )
    groups = admin.call("GET", f"/groups?search={GROUP}&exact=true")
    if not groups:
        admin.call("POST", "/groups", {"name": GROUP})
        groups = admin.call("GET", f"/groups?search={GROUP}&exact=true")
    group = next(g for g in groups if g["name"] == GROUP and g["path"] == "/" + GROUP)
    role = admin.call("GET", "/roles/profissional-rh")
    if role.get("composite"):
        raise ValueError(
            "profissional-rh deve ser um papel simples, sem permissões compostas."
        )
    existing = admin.call("GET", f"/groups/{group['id']}/role-mappings/realm/composite")
    if any(r["name"] != "profissional-rh" for r in existing):
        raise ValueError(
            "O grupo de autocadastro contém papéis inesperados. Revise antes de prosseguir."
        )
    if admin.call("GET", f"/groups/{group['id']}/role-mappings").get("clientMappings"):
        raise ValueError(
            "O grupo de autocadastro contém papéis de cliente inesperados."
        )
    admin.call("POST", f"/groups/{group['id']}/role-mappings/realm", [role])
    admin.call("PUT", f"/default-groups/{group['id']}")
    configurar_fluxo(
        admin,
        "registration",
        "synapse-registration",
        "registration-password-action",
        {"always_set_password_on_register_form": "true"},
    )
    configurar_fluxo(
        admin,
        "reset credentials",
        "synapse-reset-credentials",
        "reset-credential-email",
        {"force-login": "true"},
    )
    profile = admin.call("GET", "/users/profile")
    desired = json.loads(
        template["components"]["org.keycloak.userprofile.UserProfileProvider"][0][
            "config"
        ]["kc.user.profile.config"][0]
    )
    # Preserva atributos extras, mas os quatro campos do E11 seguem o contrato versionado.
    names = {a["name"] for a in desired["attributes"]}
    profile["attributes"] = desired["attributes"] + [
        a for a in profile["attributes"] if a["name"] not in names
    ]
    profile["unmanagedAttributePolicy"] = None
    admin.call("PUT", "/users/profile", profile)
    client = clients[0]
    admin.call(
        "PUT",
        f"/clients/{client['id']}",
        {
            "rootUrl": frontend,
            "baseUrl": frontend + "/",
            "redirectUris": [frontend + "/*"],
            "webOrigins": [frontend],
            "publicClient": True,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "attributes": client.get("attributes", {})
            | {
                "post.logout.redirect.uris": frontend + "/*",
                "pkce.code.challenge.method": "S256",
            },
        },
    )
    fields = (
        "registrationAllowed",
        "registrationEmailAsUsername",
        "loginWithEmailAllowed",
        "duplicateEmailsAllowed",
        "editUsernameAllowed",
        "resetPasswordAllowed",
        "verifyEmail",
        "internationalizationEnabled",
        "defaultLocale",
        "supportedLocales",
        "loginTheme",
        "registrationFlow",
        "resetCredentialsFlow",
        "actionTokenGeneratedByUserLifespan",
    )
    patch = {key: template[key] for key in fields}
    # Uma política de senha local mais restritiva não é enfraquecida pela atualização.
    policy = realm.get("passwordPolicy") or template["passwordPolicy"]
    patch.update(
        smtpServer=mail,
        passwordPolicy=policy,
        attributes=realm.get("attributes", {})
        | template["attributes"]
        | {"frontendUrl": public},
    )
    admin.call(
        "PUT",
        "/events/config",
        {
            "eventsEnabled": True,
            "eventsExpiration": 604800,
            "enabledEventTypes": sorted(
                set(realm.get("enabledEventTypes", []))
                | set(template["enabledEventTypes"])
            ),
            "adminEventsDetailsEnabled": False,
        },
    )
    admin.call("PUT", body=patch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", help="Arquivo CHAVE=valor, sem interpolação ou execução shell."
    )
    args = parser.parse_args()
    try:
        env = ambiente(args.env_file)
        smtp(env)
        aplicar(Admin(env), env)
        print(
            "Configuração E11 aplicada. Valide entrega de e-mail, cadastro, recuperação e login no ambiente."
        )
    except (ValueError, RuntimeError, OSError, KeyError, StopIteration) as exc:
        # Erros inesperados não imprimem configuração, resposta HTTP nem traceback.
        message = (
            str(exc)
            if isinstance(exc, (ValueError, RuntimeError))
            else "Falha ao ler ou aplicar a configuração."
        )
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
