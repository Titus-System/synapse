# Configuração do deploy de staging (droplet + CD)

Este guia cobre o passo a passo único, feito uma vez por droplet, para deixar os workflows de CD (`.github/workflows/cd-*.yml` - um por componente, mais `cd-gateway.yml` e `cd-observability.yml`) prontos para implantar em staging. Ele assume um único droplet rodando todos os serviços na mesma rede Docker (`synapse-net`), conforme decidido para a fase atual do projeto.

Todos os serviços têm subdomínio próprio, atrás de um único gateway (Caddy) que termina TLS - ver a seção 2.1 para o que isso exige de DNS antes do primeiro deploy.

Para o funcionamento normal do ambiente (subir/parar containers, healthchecks, troubleshooting), a referência é [`docs/instalacao.md`](instalacao.md) - este documento cobre só o que é específico do deploy via CD.

---

## 1. Visão geral do fluxo

- Cada `cd-<componente>.yml` dispara em `push` para a branch `staging`, filtrado por path (`api/**`, `frontend/**`, etc.) - nunca em `develop`.
- O job faz SSH no droplet, atualiza o checkout local para o commit de `staging`, e roda `docker compose build`/`up -d` **só para o serviço daquele componente**, com a imagem etiquetada pelo SHA do commit.
- Todos os workflows compartilham um único grupo de concorrência (`cd-staging-deploy`), porque todos escrevem no mesmo checkout do droplet - deploys ficam na fila em vez de rodar em paralelo.
- `postgres` e `rabbitmq` não têm workflow próprio: sobem como dependência (`depends_on`) do primeiro serviço implantado, ou manualmente no passo 3.5 abaixo.
- `frontend` não sobe como serviço de longa duração: compila o SPA e copia o resultado pro volume que o `gateway` serve, depois sai (`docker compose run --rm`, não `up -d`). O `gateway` é quem expõe 80/443 e roteia por subdomínio para os outros três - ver `deploy/gateway/Caddyfile`.

---

## 2. Pré-requisitos no droplet

- **Docker Engine** ≥ `24.0.0` e **Docker Compose** ≥ `v2.20.0` (mesma exigência do ambiente local - ver `docs/instalacao.md` §2).
- **Git** instalado.
- Um usuário com permissão de `docker` (grupo `docker`) e acesso SSH por chave.
- Portas liberadas no firewall do droplet:
  - `22` (SSH, só para o CD e administração) - considere restringir por IP se possível.
  - `80`/`443` (gateway - único serviço que fala com a internet; termina TLS pros quatro subdomínios).
  - **Não** exponha `5432`/`5672`/`15672` publicamente por enquanto - não há necessidade de acesso remoto de devs à infraestrutura de staging nesta fase.
  - `api`, `codegen` e `worker` não precisam de porta liberada no firewall externo - só são alcançados via o gateway, dentro da `synapse-net`.

### 2.1. DNS dos subdomínios

Antes de subir o gateway pela primeira vez, aponte os quatro registros DNS (tipo `A`, ou `AAAA` se o droplet tiver IPv6) para o IP do droplet:

- `GATEWAY_APP_DOMAIN` (ex.: `app.<seu-domínio>`)
- `GATEWAY_API_DOMAIN` (ex.: `api.<seu-domínio>`)
- `GATEWAY_CODEGEN_DOMAIN` (ex.: `codegen.<seu-domínio>`)
- `GATEWAY_WORKER_DOMAIN` (ex.: `worker.<seu-domínio>`)

O Caddy do gateway pede um certificado Let's Encrypt por domínio na primeira subida (HTTP-01 challenge) - se o DNS ainda não resolver pro droplet nesse momento, a emissão falha e o serviço correspondente fica sem HTTPS até você repetir a subida com o DNS já propagado.

---

## 3. Preparar o droplet

### 3.1. Criar um usuário de deploy (recomendado)

Evite usar `root` diretamente para o CD. Um usuário dedicado, no grupo `docker`, é suficiente:

```bash
sudo adduser deploy
sudo usermod -aG docker deploy
```

### 3.2. Clonar o repositório

Escolha um caminho fixo - ele será o valor do secret `STAGING_DEPLOY_PATH` (passo 5):

```bash
sudo -iu deploy
git clone --branch staging <url-do-repositorio> ~/synapse
cd ~/synapse
```

### 3.3. Configurar `deploy/.env`

```bash
cp deploy/.env.example deploy/.env
```

Preencha em `deploy/.env`:

- As senhas de banco por serviço (`SYNAPSE_API_DB_PASSWORD`, `SYNAPSE_CODEGEN_DB_PASSWORD`, `SYNAPSE_WORKER_DB_PASSWORD`) e do Postgres (`POSTGRES_PASSWORD`), com valores reais - **não deixe `troque-me`**.
- `DOCKER_GID`, com o GID do grupo `docker` **deste droplet** (`getent group docker | cut -d: -f3`) - ver `docs/instalacao.md` §2.1 para o porquê.
- `GATEWAY_APP_DOMAIN`, `GATEWAY_API_DOMAIN`, `GATEWAY_CODEGEN_DOMAIN`, `GATEWAY_WORKER_DOMAIN`, com os quatro domínios reais apontados no passo 2.1 - sem eles o gateway sobe respondendo em `*.localhost`, sem certificado válido.
- `VITE_API_BASE_URL`, com a URL completa do domínio da api (ex.: `https://api.exemplo.com`) - com subdomínio próprio por serviço, um caminho relativo (`/api`) não atravessa origem.
- `CORS_ALLOWED_ORIGINS`, com a URL do frontend (ex.: `https://app.exemplo.com`) - `app.<domínio>` e `api.<domínio>` são origens diferentes, então o navegador bloqueia toda chamada do frontend que não venha de uma origem liberada aqui. Só esquema + host (+ porta), sem caminho nem barra final; mais de uma origem, separadas por vírgula.

Esse arquivo é `.gitignore`d e fica só no droplet; o CD não o sobrescreve (só adiciona/atualiza a linha `TAG=`, usada para etiquetar a imagem pelo SHA do commit implantado).

### 3.4. Subida inicial manual

Antes do primeiro push para `staging`, suba o ambiente uma vez manualmente para validar que a infraestrutura (Postgres, RabbitMQ) inicializa corretamente - inclusive o *initdb* dos usuários por serviço, que só roda com o volume vazio:

```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --wait
docker compose -f deploy/docker-compose.yml ps
```

Confirme que todos os serviços aparecem como `healthy` (checklist completo em `docs/instalacao.md` §5) antes de prosseguir.

---

## 4. Gerar a chave SSH do CD

Gere um par de chaves dedicado ao deploy (não reutilize sua chave pessoal):

```bash
ssh-keygen -t ed25519 -C "cd-staging@synapse" -f ./cd_staging_key -N ""
```

No droplet, como o usuário `deploy`, adicione a chave **pública** (`cd_staging_key.pub`) ao `~/.ssh/authorized_keys`:

```bash
# no droplet, usuário deploy
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "<conteúdo de cd_staging_key.pub>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Guarde a chave **privada** (`cd_staging_key`) para o secret `STAGING_SSH_KEY` no passo seguinte, e depois apague a cópia local.

---

## 5. Configurar o GitHub

### 5.1. Criar o Environment `staging`

No repositório: **Settings → Environments → New environment**, nome `staging`. Todos os workflows de CD já referenciam `environment: staging` - é aqui que os secrets abaixo devem ser cadastrados (em vez de secrets de repositório), para poder aplicar regras de proteção no futuro, se necessário.

### 5.2. Cadastrar os secrets

Em **Settings → Environments → staging → Environment secrets**:

| Secret | Valor |
| --- | --- |
| `STAGING_SSH_HOST` | IP ou hostname do droplet |
| `STAGING_SSH_USER` | `deploy` (ou o usuário escolhido no passo 3.1) |
| `STAGING_SSH_KEY` | Conteúdo da chave **privada** gerada no passo 4 |
| `STAGING_DEPLOY_PATH` | Caminho absoluto do clone no droplet (ex.: `/home/deploy/synapse`) |

---

## 6. Validar o primeiro deploy automático

1. Faça um push (ou merge de PR) para `staging` que toque em algum dos diretórios `api/`, `frontend/`, `codegen/`, `worker/`, `deploy/gateway/` ou `deploy/observability/`.
2. Acompanhe a run correspondente em **Actions** (`cd-api`, `cd-frontend`, `cd-codegen`, `cd-worker`, `cd-gateway` ou `cd-observability`).
3. No droplet, confirme a imagem etiquetada e o container recriado:

   ```bash
   docker compose -f deploy/docker-compose.yml --env-file deploy/.env ps
   docker images | grep synapse-
   ```

   Para o `frontend`, "recriado" não se aplica - confirme pelo log da run do Actions que o `run --rm` terminou com sucesso (o container não fica listado no `ps`, ele roda e sai).

4. Rode o healthcheck do serviço implantado (endpoints em `docs/instalacao.md` §4 para `api`/`codegen`/`worker`; para `frontend` e `gateway`, acesse `https://<GATEWAY_APP_DOMAIN>` no navegador).

Se algo falhar, os logs do passo SSH aparecem diretamente na run do Actions - não é preciso acessar o droplet para o primeiro diagnóstico.

---

## 7. Referência rápida dos workflows

| Workflow | Dispara em | Roda no droplet |
| --- | --- | --- |
| `cd-api.yml` | push em `staging` tocando `api/**` | `docker compose build/up -d api` |
| `cd-frontend.yml` | push em `staging` tocando `frontend/**` | `docker compose build frontend` + `run --rm frontend` (copia o dist pro volume do gateway) |
| `cd-codegen.yml` | push em `staging` tocando `codegen/**` | `docker compose build/up -d codegen` |
| `cd-worker.yml` | push em `staging` tocando `worker/**` | `docker compose build/up -d worker` |
| `cd-gateway.yml` | push em `staging` tocando `deploy/gateway/**` | `docker compose up -d --force-recreate gateway` |
| `cd-observability.yml` | push em `staging` tocando `deploy/observability/**` | `docker compose up -d --force-recreate` (compose de observabilidade) |

Nenhum deles dispara em `develop` - essa branch passa apenas pela CI de verificação (`verificar-api.yml` e futuros equivalentes por componente).

---

## 8. Observabilidade (Grafana Cloud + Alloy)

Conforme o [ADR-004](adrs/ADR-004.md), cada serviço só emite log estruturado em stdout e expõe `/metrics` - quem coleta e envia é o **Grafana Alloy**, um agente por host. Como o backend escolhido é **Grafana Cloud** (não self-hosted), Loki/Prometheus/Grafana/Alertmanager não rodam neste droplet; só o Alloy roda localmente e empurra tudo pra lá.

A stack de observabilidade fica num compose **separado** da aplicação (`deploy/observability/docker-compose.yml`), com ciclo de vida independente do `deploy/docker-compose.yml` - subir, atualizar ou derrubar o Alloy não afeta o deploy dos quatro serviços. Assim como os componentes, ele tem seu próprio workflow de CD: `cd-observability.yml` dispara em push para `staging` tocando `deploy/observability/**` e recria o container (`--force-recreate`, sem build - a imagem do Alloy é pinada, vem pronta do Docker Hub) pra sempre reler o `config.alloy` e o `.env` atuais do droplet.

### 8.1. Criar a conexão Alloy no Grafana Cloud

1. No Grafana Cloud, abra sua stack → **Connections** → **Add new connection** → **Alloy** → método **Docker**.
2. O assistente gera as credenciais reais da sua conta/região (URLs de push de métricas e logs, IDs de instância, API key com escopo `metrics:write` + `logs:write`).
3. **Guarde esse snippet** - ele é a fonte de verdade para os valores do passo 8.3. O `deploy/observability/config.alloy` já commitado é um ponto de partida com os mesmos nomes de variável que o assistente costuma gerar, mas confira antes de usar: sintaxe do Alloy e nomes podem mudar entre versões/contas.

### 8.2. Pré-requisito: a rede `synapse-net` já precisa existir

O compose de observabilidade referencia `synapse-net` como rede **externa** (`external: true`) - ela só existe depois que a aplicação (`deploy/docker-compose.yml`) subiu ao menos uma vez. Suba a aplicação (seção 3.5) antes deste passo.

### 8.3. Configurar e subir o Alloy

```bash
cd deploy/observability
cp .env.example .env
```

Preencha `deploy/observability/.env` com os valores reais obtidos no passo 8.1 (`GCLOUD_HOSTED_METRICS_URL`, `GCLOUD_HOSTED_METRICS_ID`, `GCLOUD_HOSTED_LOGS_URL`, `GCLOUD_HOSTED_LOGS_ID`, `GCLOUD_RW_API_KEY`) - nunca os valores de exemplo do `.env.example`.

```bash
docker compose -f deploy/observability/docker-compose.yml up -d
docker compose -f deploy/observability/docker-compose.yml logs -f alloy
```

Espere o log confirmar a conexão com os endpoints remote_write, sem erros de autenticação.

Isso é só a subida inicial (o `.env` não vem do git, então precisa existir no droplet antes do primeiro deploy). Depois disso, qualquer mudança em `deploy/observability/**` mergeada em `staging` implanta sozinha via `cd-observability.yml` - não repita este passo manualmente para alterações de config.

### 8.4. Validar

- No Grafana Cloud, painel **Explore** → fonte **Loki**: consulte `{job="synapse"}` e confirme que os logs JSON dos quatro serviços aparecem.
- **Explore** → fonte **Prometheus/Mimir**: consulte `up{job=~"synapse-.*"}` e confirme os três alvos (`synapse-api`, `synapse-codegen`, `synapse-worker`) em `1`.
- Correlação por `job_id`: filtre um log de um job em andamento pelo campo `job_id` (`contracts/observability/log.schema.json`) e confirme que aparece nos três serviços de backend.

### 8.5. Notas

- A UI local de debug do Alloy fica em `127.0.0.1:12345` no droplet, não exposta publicamente - use um túnel SSH (`ssh -L 12345:localhost:12345 <usuário>@<droplet>`) se precisar dela.
- `deploy/observability/.env` é `.gitignore`d, assim como `deploy/.env` - as credenciais nunca vão pro repositório.
- Trocar Grafana Cloud por self-hosted no futuro é reconfiguração do `config.alloy` (troca dos blocos `remote_write`/`loki.write` pelos endpoints locais), sem mudar nenhum dos quatro serviços - é exatamente a garantia que o ADR-004 registra.
