# Manual de Instalação e Execução da Infraestrutura Local

Este documento orienta a inicialização e operação do ambiente local do projeto **Synapse** via Docker Compose.

O ambiente de infraestrutura fornece autenticação pelo Keycloak, persistência de dados e mensageria assíncrona para os quatro componentes de desenvolvimento (`frontend`, `api`, `codegen` e `worker`), conforme definido em [ADR-001](../docs/adrs/ADR-001.md) e [ARCHITECTURE.md](../docs/ARCHITECTURE.md).

---

## 1. Serviços Contemplados

A infraestrutura local inclui os serviços abaixo:

1. **PostgreSQL 18**: Armazenamento único do sistema (armazena estado dos jobs, artefatos gerados, checkpoints e trilhas de auditoria). Configurado com volume persistente e criação automática do banco `synapse_db`.
2. **RabbitMQ 3.13 (com Management UI)**: Broker de mensageria assíncrona para troca de eventos e comandos entre a API e os workers, com painel administrativo web exposto.
3. **API**: aplicação Spring Boot que expõe health check e métricas de infraestrutura.
4. **codegen**: Processo FastAPI que expõe somente os endpoints operacionais de saúde e métricas.
5. **worker**: Processo que consome a fila de execução e sobe os containers efêmeros do sandbox. Diferente dos demais, ele precisa alcançar o **daemon do Docker do host** — ver a seção 2.1.
6. **Keycloak 26.7.4**: Provedor OIDC de identidade. Importa o realm `synapse` e o cliente público `synapse-frontend`, com login local em `http://localhost:8081`.
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

### 2.1. Acesso do `worker` ao daemon do Docker

O `worker` é o único componente que executa código gerado por IA, e o faz subindo um container efêmero por execução. Para isso ele recebe o socket do Docker do host montado dentro do próprio container:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

O container do `worker` roda como usuário sem privilégios (`appuser`, uid 1000), e o socket pertence ao grupo `docker` do host. Sem estar nesse grupo, o processo enxerga o arquivo mas recebe *permission denied* ao usá-lo. Por isso o compose precisa do **GID do grupo `docker` da sua máquina**.

**Esse número varia entre distribuições — descubra o da sua e não copie o de outra pessoa:**

```bash
getent group docker | cut -d: -f3
```

Coloque o valor retornado em `deploy/.env`:

```bash
DOCKER_GID=984   # troque pelo número que o comando acima devolveu
```

O compose não sobe sem essa variável: ela é declarada como obrigatória justamente para falhar com mensagem clara, em vez de deixar o `worker` subir e quebrar só na primeira execução.

> **Nota de segurança:** montar o socket dá ao `worker` controle sobre o daemon do host, o que equivale a acesso root na máquina. É uma consequência aceita do desenho — o `worker` existe para conter código não confiável em containers descartáveis, e quem cria esses containers precisa falar com o daemon. O código gerado nunca roda no processo do `worker`, apenas dentro do container efêmero, que não tem acesso ao socket.

**Usuários de Docker Desktop (macOS/Windows) e Rootless Docker:** o caminho e a propriedade do socket mudam nesses ambientes. No Docker Desktop, use `DOCKER_GID=0`. No Rootless Docker, o socket fica em `$XDG_RUNTIME_DIR/docker.sock` e o `worker` precisa apontar para lá pela variável `DOCKER_HOST`.

---

## 3. Inicialização Rápida (Comando Único)

Antes do primeiro uso, crie `deploy/.env` a partir de `deploy/.env.example`, caso o arquivo ainda não exista. Preencha as credenciais dos serviços, `DOCKER_GID` e `KEYCLOAK_ADMIN_PASSWORD`. O Compose exige essas variáveis mesmo em comandos que selecionam apenas um serviço.

```bash
cp deploy/.env.example deploy/.env
```

Use `--env-file deploy/.env` ao executar os comandos da raiz do repositório. A configuração de usuários da aplicação e do frontend está no [guia do Keycloak local](../deploy/keycloak/README.md).

### Antes do primeiro `up`: a imagem do sandbox

O `worker` executa cada job num container criado a partir da imagem `synapse-sandbox`, e essa imagem não sobe com o `up`: ela só é construída. Construa-a uma vez, e de novo quando `worker/sandbox/` mudar. Sem ela, o `worker` sobe normalmente, mas todo comando de execução falha e acaba na fila de DLQ.

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml --profile build build sandbox
```

### Opção A: A partir da raiz do repositório

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
```

### Opção B: A partir do diretório `deploy/`

```bash
cd deploy
docker compose up -d
```

> **Dica:** Para que o comando aguarde até que todos os serviços passem nos seus respectivos *healthchecks* antes de liberar o terminal, utilize a flag `--wait`:
>
> ```bash
> docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --wait
> ```

---

## 4. Tabela de Serviços, Portas e Credenciais

Os nomes de host, portas e credenciais abaixo são padronizados para desenvolvimento local e **não devem ser alterados** durante a sprint para não impactar a configuração dos microsserviços dependentes.

| Serviço | Nome do Container | Hostname na rede (`synapse-net`) | Porta no Host | Porta Interna | Usuário Padrão | Senha Padrão | Banco / VHost | URL / Interface de Acesso |
| :--- | :--- | :--- | :---: | :---: | :--- | :--- | :--- | :--- |
| **PostgreSQL** | `synapse-postgres` | `postgres` | `5432` | `5432` | `postgres` | `postgres` | `synapse_db` | `postgresql://postgres:postgres@localhost:5432/synapse_db` |
| **RabbitMQ (AMQP)** | `synapse-rabbitmq` | `rabbitmq` | `5672` | `5672` | `guest` | `guest` | `/` | `amqp://guest:guest@localhost:5672` |
| **RabbitMQ (Painel)** | `synapse-rabbitmq` | `rabbitmq` | `15672` | `15672` | `guest` | `guest` | — | [http://localhost:15672](http://localhost:15672) |
| **codegen** | `synapse-infra-codegen-1` | `codegen` | `8001` | `8000` | — | — | — | [http://localhost:8001/health](http://localhost:8001/health) |
| **worker** | `synapse-infra-worker-1` | `worker` | `8002` | `8000` | — | — | — | [http://localhost:8002/health](http://localhost:8002/health) |
| **API** | `synapse-infra-api-1` | `api` | `8080` | `8080` | — | — | — | [http://localhost:8080/actuator/health](http://localhost:8080/actuator/health) |
| **Keycloak** | `synapse-keycloak` | `keycloak` | `8081` | `8080` | `KEYCLOAK_ADMIN_USERNAME` | `KEYCLOAK_ADMIN_PASSWORD` | realm `synapse` | [http://localhost:8081/admin/](http://localhost:8081/admin/) |

As variáveis de ambiente estão documentadas em `deploy/.env.example`; `deploy/.env` deve fornecer as variáveis obrigatórias descritas na seção 3.

---

## 5. Verificação de Saúde (Healthcheck)

Confira o status **`healthy`** dos serviços que possuem *healthcheck*. O Keycloak não tem *healthcheck* configurado no Compose; valide sua inicialização pelo endpoint OIDC abaixo. O frontend do Compose é uma tarefa de build e cópia, que termina após concluir essa operação:

Execute:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
```

Saída esperada:

```text
NAME               IMAGE                             STATUS                   PORTS
synapse-postgres   postgres:16-alpine                Up (healthy)             0.0.0.0:5432->5432/tcp
synapse-rabbitmq   rabbitmq:3.13-management-alpine   Up (healthy)             0.0.0.0:5672->5672/tcp, 0.0.0.0:15672->15672/tcp
synapse-infra-codegen-1 synapse-codegen:local         Up (healthy)             0.0.0.0:8001->8000/tcp
synapse-infra-api-1 synapse-api:local                Up (healthy)             0.0.0.0:8080->8080/tcp
```

### Testando conectividade direta:

1. **PostgreSQL**:

   ```bash
   docker exec synapse-postgres pg_isready -U postgres -d synapse_db
   # Retorno esperado: /var/run/postgresql:5432 - accepting connections
   ```

   O usuário `postgres` da tabela acima é o **dono do schema**: só as migrations da API o usam. Cada serviço conecta com um usuário próprio (`synapse_api`, `synapse_codegen`, `synapse_worker`), com a senha definida em `deploy/.env`.

2. **RabbitMQ**:
   Abra no seu navegador o endereço [http://localhost:15672](http://localhost:15672) e faça login com usuário `guest` e senha `guest`. O painel de administração deverá carregar com visão geral das conexões e exchanges.

3. **codegen**:

   ```bash
   curl --fail http://localhost:8001/health
   # Retorno esperado: {"status":"UP"}
   ```
  
4. **API**:

   ```bash
   curl --fail http://localhost:8080/actuator/health
   # Retorno esperado: {"status":"UP"}
   ```

5. **worker**:

   ```bash
   curl --fail http://localhost:8002/health
   # Retorno esperado: "ok"
   ```

   O `worker` verifica o acesso ao daemon e declara a fila durante a subida. Os dois ficam registrados no log:

   ```bash
   docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs worker | grep -E "daemon|fila"
   ```

   ```json
   {"message":"acesso ao daemon do Docker verificado","extra":{"containers_em_execucao":5}}
   {"message":"fila de execução declarada","extra":{"fila":"executar-codigo","prefetch":1}}
   ```

   Se essas linhas não aparecem, o processo não subiu - confira a seção 7.

6. **Keycloak**:

   ```bash
   curl --fail http://localhost:8081/realms/synapse/.well-known/openid-configuration
   ```

   O endpoint deve devolver o documento OIDC com `issuer` igual a `http://localhost:8081/realms/synapse`. Para testar login, renovação e logout pelo frontend, siga o [guia do Keycloak](../deploy/keycloak/README.md).

---

## 6. Ciclo de Vida e Persistência de Dados

### Parar os serviços preservando os dados

Para interromper a infraestrutura sem perder tabelas, registros ou filas:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down
```

Os volumes nomeados preservam os dados de PostgreSQL (`synapse-postgres-data`), RabbitMQ (`synapse-rabbitmq-data`) e Keycloak (`keycloak-data` no Compose). Ao subir os serviços novamente, esses volumes são reutilizados, incluindo os usuários e o realm do Keycloak.

### Reiniciar os serviços

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml restart
```

### Resetar o ambiente (Destruição total de dados)

Caso precise recriar os bancos, filas e a configuração do Keycloak totalmente do zero (apagando também seus usuários, realm e sessões persistidas):

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down -v
```

---

## 7. Resolução de Problemas (Troubleshooting)

### Porta já em uso (`bind: address already in use`)

Se você já tiver instâncias locais de PostgreSQL (porta 5432) ou RabbitMQ (porta 5672 / 15672) rodando nativamente no seu sistema operacional, o Docker não conseguirá vincular a porta.

- **Solução:** Pare os serviços locais (ex.: `sudo systemctl stop postgresql`) antes de subir o compose, ou ajuste as portas em `deploy/.env`.

### O `worker` não sobe: sem acesso ao daemon do Docker

Se o compose recusa a subida com `defina em deploy/.env; ver docs/instalacao.md`, falta a variável `DOCKER_GID` — volte à seção 2.1.

Se o container do `worker` sobe e morre em seguida, o log traz a causa:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs worker | tail -20
```

```text
DaemonIndisponivelError: sem acesso ao daemon do Docker em unix:///var/run/docker.sock
```

O `worker` derruba o processo de propósito nesse caso, em vez de subir e falhar só na primeira execução. As causas prováveis, em ordem:

1. **`DOCKER_GID` com o número errado.** É o caso mais comum, porque o GID muda de máquina para máquina. Reveja com `getent group docker | cut -d: -f3` e recrie o container (`docker compose up -d --force-recreate worker`) — mudar o `.env` sozinho não basta.
2. **Socket em outro caminho.** Rootless Docker e Docker Desktop não usam `/var/run/docker.sock`; ajuste `DOCKER_HOST`.
3. **Daemon parado no host.** Confirme com `docker info` na sua máquina, fora do compose.

### Consultar logs de um serviço

Para acompanhar a saída de logs em tempo real:

```bash
# Todos os serviços
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs -f

# Somente Postgres
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs -f postgres

# Somente RabbitMQ
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs -f rabbitmq
```
