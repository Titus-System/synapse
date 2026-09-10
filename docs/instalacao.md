# Manual de Instalação e Execução da Infraestrutura Local

Este documento orienta a inicialização e operação dos serviços de infraestrutura local do projeto **Synapse** via Docker Compose.

O ambiente de infraestrutura fornece a base de persistência de dados e mensageria assíncrona para os quatro componentes de desenvolvimento (`frontend`, `api`, `codegen` e `worker`), conforme definido em [ADR-001](../docs/adrs/ADR-001.md) e [ARCHITECTURE.md](../docs/ARCHITECTURE.md).

---

## 1. Serviços Contemplados

A infraestrutura local é composta pelos serviços de infraestrutura e pelo codegen:

1. **PostgreSQL 16**: Armazenamento único do sistema (armazena estado dos jobs, artefatos gerados, checkpoints e trilhas de auditoria). Configurado com volume persistente e criação automática do banco `api_db`.
2. **RabbitMQ 3.13 (com Management UI)**: Broker de mensageria assíncrona para troca de eventos e comandos entre a API e os workers, com painel administrativo web exposto.
3. **codegen**: Processo FastAPI que expõe somente os endpoints operacionais de saúde e métricas.

*(Nota: `api`, `worker`, `frontend` e a stack de observabilidade serão integrados em tarefas dedicadas posteriores).*

---

## 2. Pré-requisitos

Certifique-se de possuir instalado no seu ambiente:

- **Docker Engine** versão `24.0.0` ou superior (ou **Docker Desktop**)
- **Docker Compose** versão `v2.20.0` ou superior

Para verificar suas versões, execute:

```bash
docker --version
docker compose version
```

---

## 3. Inicialização Rápida (Comando Único)

Todo o ambiente de infraestrutura sobe com um único comando, sem necessidade de configuração manual adicional:

### Opção A: A partir da raiz do repositório

```bash
docker compose -f deploy/docker-compose.yml up -d
```

### Opção B: A partir do diretório `deploy/`

```bash
cd deploy
docker compose up -d
```

> **Dica:** Para que o comando aguarde até que todos os serviços passem nos seus respectivos *healthchecks* antes de liberar o terminal, utilize a flag `--wait`:
>
> ```bash
> docker compose -f deploy/docker-compose.yml up -d --wait
> ```

---

## 4. Tabela de Serviços, Portas e Credenciais

Os nomes de host, portas e credenciais abaixo são padronizados para desenvolvimento local e **não devem ser alterados** durante a sprint para não impactar a configuração dos microsserviços dependentes.

| Serviço | Nome do Container | Hostname na rede (`synapse-net`) | Porta no Host | Porta Interna | Usuário Padrão | Senha Padrão | Banco / VHost | URL / Interface de Acesso |
| :--- | :--- | :--- | :---: | :---: | :--- | :--- | :--- | :--- |
| **PostgreSQL** | `synapse-postgres` | `postgres` | `5432` | `5432` | `postgres` | `postgres` | `api_db` | `postgresql://postgres:postgres@localhost:5432/api_db` |
| **RabbitMQ (AMQP)** | `synapse-rabbitmq` | `rabbitmq` | `5672` | `5672` | `guest` | `guest` | `/` | `amqp://guest:guest@localhost:5672` |
| **RabbitMQ (Painel)** | `synapse-rabbitmq` | `rabbitmq` | `15672` | `15672` | `guest` | `guest` | — | [http://localhost:15672](http://localhost:15672) |
| **codegen** | `synapse-infra-codegen-1` | `codegen` | `8001` | `8000` | — | — | — | [http://localhost:8001/health](http://localhost:8001/health) |

As variáveis de ambiente padrão estão declaradas e versionadas em `deploy/.env.example` (copie para `deploy/.env` se quiser sobrescrever os defaults do compose).

---

## 5. Verificação de Saúde (Healthcheck)

Cada serviço possui um *healthcheck* configurado. O ambiente só é considerado pronto quando todos os containers estiverem com status **`healthy`**:

Execute:

```bash
docker compose -f deploy/docker-compose.yml ps
```

Saída esperada:

```text
NAME               IMAGE                             STATUS                   PORTS
synapse-postgres   postgres:16-alpine                Up (healthy)             0.0.0.0:5432->5432/tcp
synapse-rabbitmq   rabbitmq:3.13-management-alpine   Up (healthy)             0.0.0.0:5672->5672/tcp, 0.0.0.0:15672->15672/tcp
synapse-infra-codegen-1 synapse-codegen:local         Up (healthy)             0.0.0.0:8001->8000/tcp
```

### Testando conectividade direta:

1. **PostgreSQL**:

   ```bash
   docker exec synapse-postgres pg_isready -U postgres -d api_db
   # Retorno esperado: /var/run/postgresql:5432 - accepting connections
   ```

2. **RabbitMQ**:
   Abra no seu navegador o endereço [http://localhost:15672](http://localhost:15672) e faça login com usuário `guest` e senha `guest`. O painel de administração deverá carregar com visão geral das conexões e exchanges.

3. **codegen**:

   ```bash
   curl --fail http://localhost:8001/health
   # Retorno esperado: {"status":"UP"}
   ```

---

## 6. Ciclo de Vida e Persistência de Dados

### Parar os serviços preservando os dados

Para interromper a infraestrutura sem perder tabelas, registros ou filas:

```bash
docker compose -f deploy/docker-compose.yml down
```

Os dados permanecem seguros nos volumes nomeados Docker (`synapse-postgres-data` e `synapse-rabbitmq-data`). Ao rodar `docker compose up -d` novamente, todo o estado anterior é restaurado.

### Reiniciar os serviços

```bash
docker compose -f deploy/docker-compose.yml restart
```

### Resetar o ambiente (Destruição total de dados)

Caso precise recriar os bancos e filas totalmente do zero (apagando todos os dados persistidos):

```bash
docker compose -f deploy/docker-compose.yml down -v
```

---

## 7. Resolução de Problemas (Troubleshooting)

### Porta já em uso (`bind: address already in use`)

Se você já tiver instâncias locais de PostgreSQL (porta 5432) ou RabbitMQ (porta 5672 / 15672) rodando nativamente no seu sistema operacional, o Docker não conseguirá vincular a porta.

- **Solução:** Pare os serviços locais (ex.: `sudo systemctl stop postgresql`) antes de subir o compose, ou ajuste as portas em `deploy/.env`.

### Consultar logs de um serviço

Para acompanhar a saída de logs em tempo real:

```bash
# Todos os serviços
docker compose -f deploy/docker-compose.yml logs -f

# Somente Postgres
docker compose -f deploy/docker-compose.yml logs -f postgres

# Somente RabbitMQ
docker compose -f deploy/docker-compose.yml logs -f rabbitmq
```
