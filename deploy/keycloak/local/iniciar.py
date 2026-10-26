"""Inicializa o E11 local em Windows/Linux com Docker e o Python que o executou."""

import argparse
import importlib.util
import os
import secrets
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path
from urllib import request

LOCAL = Path(__file__).resolve().parent
KEYCLOAK = LOCAL.parent
REPO = KEYCLOAK.parents[1]
ENV_FILE = LOCAL / ".env"
CHAVES = ("E11_ADMIN_PASSWORD", "E11_DB_PASSWORD", "E11_BROKER_PASSWORD")


def ambiente_local():
    if not ENV_FILE.exists():
        with ENV_FILE.open("x", encoding="utf-8") as arquivo:
            arquivo.write(
                "# Gerado para este ambiente local. Não versione nem apague com volumes existentes.\n"
            )
            for chave in CHAVES:
                arquivo.write(f"{chave}={secrets.token_urlsafe(24)}\n")
        print(
            "[E11] Configuração local criada em deploy/keycloak/local/.env.", flush=True
        )
    valores = {}
    for linha in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        if linha and not linha.startswith("#"):
            chave, _, valor = linha.partition("=")
            valores[chave] = valor
    if any(not valores.get(chave) for chave in CHAVES):
        raise RuntimeError(
            "O .env local está incompleto. Preserve as senhas dos volumes existentes e preencha as três chaves E11_."
        )
    return valores


def executar(args, *, env=None, timeout=1800):
    subprocess.run(args, cwd=REPO, env=env, check=True, timeout=timeout)


def compose(*args, testes=False):
    arquivo = KEYCLOAK / "tests/compose.yml" if testes else LOCAL / "compose.yml"
    comando = [
        "docker",
        "compose",
        "-p",
        "synapse-e11-test" if testes else "synapse-e11-local",
    ]
    if not testes:
        comando += ["--env-file", str(ENV_FILE)]
    return comando + ["-f", str(arquivo), *args]


def env_docker():
    # Exportações de outros ambientes não substituem as senhas do .env local.
    return {
        k: v
        for k, v in os.environ.items()
        if k not in CHAVES
        and k not in ("COMPOSE_FILE", "COMPOSE_PROFILES", "COMPOSE_PROJECT_NAME")
    }


def verificar_docker():
    if not shutil.which("docker"):
        raise RuntimeError(
            "Instale e abra o Docker Desktop com containers Linux antes de continuar."
        )
    resultado = subprocess.run(
        ["docker", "info", "--format", "{{.OSType}}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if resultado.returncode or resultado.stdout.strip() != "linux":
        raise RuntimeError(
            "O Docker Desktop precisa estar iniciado e usando containers Linux."
        )
    executar(["docker", "compose", "version"], timeout=30)


def configurar(valores):
    spec = importlib.util.spec_from_file_location(
        "configurar", KEYCLOAK / "configurar.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    env = {
        "KEYCLOAK_ADMIN_URL": "http://localhost:8081",
        "KEYCLOAK_PUBLIC_URL": "http://localhost:8081",
        "KEYCLOAK_ADMIN_USERNAME": "admin",
        "KEYCLOAK_ADMIN_PASSWORD": valores["E11_ADMIN_PASSWORD"],
        "SYNAPSE_FRONTEND_URL": "http://localhost:5173",
        "KEYCLOAK_SMTP_HOST": "mailpit",
        "KEYCLOAK_SMTP_PORT": "1025",
        "KEYCLOAK_SMTP_FROM": "synapse@example.test",
        "KEYCLOAK_SMTP_AUTH": "false",
        "KEYCLOAK_SMTP_STARTTLS": "false",
        "KEYCLOAK_SMTP_SSL": "false",
        "KEYCLOAK_SMTP_ALLOW_INSECURE": "true",
    }
    modulo.aplicar(modulo.Admin(env), env)


def verificar_http(url):
    opener = request.build_opener(request.ProxyHandler({}))
    with opener.open(url, timeout=10) as resposta:
        if resposta.status != 200:
            raise RuntimeError("Um dos serviços locais não respondeu com sucesso.")


def testar():
    pasta = LOCAL / ".venv"
    python = pasta / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("[E11] Criando ambiente Python exclusivo dos testes...", flush=True)
        venv.EnvBuilder(with_pip=True).create(pasta)
    executar(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(KEYCLOAK / "tests/requirements.txt"),
            "-r",
            str(REPO / "deploy/scripts/requirements.txt"),
        ]
    )
    env = env_docker() | {
        "KEYCLOAK_E2E_URL": "http://localhost:8180",
        "KEYCLOAK_E2E_METRICS_URL": "http://localhost:9000/metrics",
        "KEYCLOAK_E2E_MAILPIT_URL": "http://localhost:8026",
        "KEYCLOAK_E2E_SMTP_HOST": "mailpit",
        "KEYCLOAK_ADMIN_USERNAME": "admin",
        "KEYCLOAK_ADMIN_PASSWORD": "e11-local-tests-only",
    }
    # O teste visual opcional tem dependências próprias, descritas no README.
    env.pop("SYNAPSE_TEST_CHROMIUM", None)
    try:
        executar(
            compose("up", "-d", "--wait", "--wait-timeout", "240", testes=True), env=env
        )
        print(
            "[E11] Executando testes. As etapas e suas durações aparecerão abaixo.",
            flush=True,
        )
        executar(
            [
                str(python),
                "-u",
                "-m",
                "unittest",
                "discover",
                "-s",
                "deploy/keycloak/tests",
                "-v",
                "-f",
            ],
            env=env,
            timeout=600,
        )
    finally:
        executar(compose("down", testes=True), env=env, timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "acao",
        nargs="?",
        default="iniciar",
        choices=("iniciar", "parar", "status", "testar", "logs"),
    )
    args = parser.parse_args()
    inicio = time.monotonic()
    verificar_docker()
    if args.acao == "testar":
        testar()
        return
    valores = ambiente_local()
    env = env_docker()
    if args.acao == "parar":
        executar(compose("down"), env=env, timeout=120)
        print("Ambiente parado. Contas e dados foram preservados.")
        return
    if args.acao == "status":
        executar(compose("ps"), env=env, timeout=30)
        return
    if args.acao == "logs":
        executar(
            compose("logs", "--tail", "80", "keycloak", "api", "mailpit"),
            env=env,
            timeout=30,
        )
        return
    print(
        "[1/5] Compilando API e frontend. O primeiro build pode levar vários minutos.",
        flush=True,
    )
    executar(compose("build", "api", "frontend-build"), env=env)
    print("[2/5] Publicando os arquivos do frontend local.", flush=True)
    executar(
        compose("run", "--rm", "--no-deps", "frontend-build"), env=env, timeout=120
    )
    print("[3/5] Iniciando banco, mensageria, e-mail, Keycloak e API.", flush=True)
    executar(
        compose(
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "300",
            "postgres",
            "rabbitmq",
            "mailpit",
            "keycloak",
            "api",
        ),
        env=env,
        timeout=900,
    )
    print("[4/5] Configurando o realm synapse e o envio para o Mailpit.", flush=True)
    configurar(valores)
    print("[5/5] Iniciando o acesso pelo navegador.", flush=True)
    executar(
        compose("up", "-d", "--wait", "--wait-timeout", "120", "frontend"),
        env=env,
        timeout=180,
    )
    for url in (
        "http://localhost:5173",
        "http://localhost:8080/actuator/health",
        "http://localhost:8025/readyz",
    ):
        verificar_http(url)
    print(f"\nAmbiente pronto em {time.monotonic() - inicio:.0f}s.")
    print("Synapse: http://localhost:5173/nova-regra")
    print("E-mails de teste: http://localhost:8025")
    print(
        "Keycloak: http://localhost:8081/admin/ (admin; senha E11_ADMIN_PASSWORD no .env local)"
    )
    print(
        "Cadastre uma conta como pessoa@example.test e abra a verificação na caixa de e-mail local."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(
            "\nInterrompido. Use a ação status para conferir os containers.",
            file=sys.stderr,
        )
        sys.exit(130)
    except subprocess.TimeoutExpired:
        print(
            "\nTempo limite atingido. Use a ação logs; confira Docker, rede e recursos disponíveis.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        # Não imprime payloads administrativos, senhas ou links com tokens.
        mensagem = (
            str(exc)
            if isinstance(exc, (RuntimeError, ValueError))
            else "Um comando falhou. Confira a saída acima e execute a ação logs."
        )
        print(f"\nE11: {mensagem}", file=sys.stderr)
        sys.exit(1)
