"""`rabbitmqctl` do RabbitMQ do compose, para os testes que precisam de um vhost isolado e de
contagens que só o broker sabe (mensagens prontas, sem `ack` e consumidores)."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.yml"


def rabbitmqctl(*argumentos: str) -> str:
    resultado = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "exec",
            "-T",
            "rabbitmq",
            "rabbitmqctl",
            *argumentos,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return resultado.stdout


@dataclass(frozen=True)
class ContagemDaFila:
    prontas: int
    sem_ack: int
    consumidores: int

    @property
    def vazia(self) -> bool:
        """Nada esperando nem em mãos de um consumidor sem `ack`."""
        return self.prontas == 0 and self.sem_ack == 0


def contagens_das_filas(vhost: str) -> dict[str, ContagemDaFila]:
    """O que o broker sabe agora, fila por fila. Diferente de um `get`, enxerga a mensagem que um
    consumidor recebeu e ainda não confirmou."""
    saida = rabbitmqctl(
        "--quiet",
        "list_queues",
        "-p",
        vhost,
        "name",
        "messages_ready",
        "messages_unacknowledged",
        "consumers",
        "--no-table-headers",
    )
    contagens: dict[str, ContagemDaFila] = {}
    for linha in saida.splitlines():
        campos = linha.split()
        if len(campos) == 4:
            nome, prontas, sem_ack, consumidores = campos
            contagens[nome] = ContagemDaFila(int(prontas), int(sem_ack), int(consumidores))
    return contagens
