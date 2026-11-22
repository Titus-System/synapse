# Manual de Instalação e Execução do Ambiente Local

Este manual explica como preparar uma máquina **Linux**, **Windows** ou **macOS** e subir o ambiente local completo do **Synapse** com Docker Compose: banco, mensageria, autenticação, `api`, `codegen`, `worker` e o `frontend` em modo de desenvolvimento.

A arquitetura dos componentes está em [ARCHITECTURE.md](ARCHITECTURE.md) e a comunicação entre eles em [ADR-001](adrs/ADR-001.md). Este documento trata somente da instalação e da operação local.

## Sumário

1. [Visão geral do ambiente](#1-visão-geral-do-ambiente)
2. [Requisitos de máquina](#2-requisitos-de-máquina)
3. [Preparar o sistema operacional](#3-preparar-o-sistema-operacional)
4. [Obter o código](#4-obter-o-código)
5. [Configurar as variáveis de ambiente](#5-configurar-as-variáveis-de-ambiente)
6. [Construir as imagens](#6-construir-as-imagens)
7. [Subir os serviços](#7-subir-os-serviços)
8. [Executar o frontend](#8-executar-o-frontend)
9. [Criar um usuário de acesso](#9-criar-um-usuário-de-acesso)
10. [Verificar a instalação](#10-verificar-a-instalação)
11. [Tabela de serviços, portas e credenciais](#11-tabela-de-serviços-portas-e-credenciais)
12. [Ciclo de vida e persistência de dados](#12-ciclo-de-vida-e-persistência-de-dados)
13. [Resolução de problemas](#13-resolução-de-problemas)
14. [Referência rápida de comandos por sistema](#14-referência-rápida-de-comandos-por-sistema)

---

## 1. Visão geral do ambiente

Todos os serviços são definidos em `deploy/docker-compose.yml`, no projeto Compose `synapse-infra`, e compartilham a rede Docker `synapse-net`.

| Serviço | O que faz | Sobe com `up`? |
| :--- | :--- | :---: |
| **postgres** (PostgreSQL 18) | Armazenamento único do sistema: estado dos jobs, artefatos gerados, checkpoints e trilha de auditoria. Na primeira subida cria o banco `synapse_db` e um usuário de banco por serviço. | Sim |
| **rabbitmq** (RabbitMQ 3.13 com Management UI) | Broker de mensageria assíncrona entre `api`, `codegen` e `worker`, com painel web. | Sim |
| **keycloak** (Keycloak 26.7.4) | Provedor de identidade OIDC. Importa o realm `synapse` e o cliente público `synapse-frontend`. | Sim |
| **api** (Spring Boot, Java 21) | REST, SSE, autenticação, estado do job. Aplica as migrations do banco ao iniciar. | Sim |
| **codegen** (Python, FastAPI, LangGraph) | Interpreta a regra e gera o código com auxílio de LLM. | Sim |
| **worker** (Python) | Consome a fila de execução e roda o código gerado em containers efêmeros do sandbox. Precisa alcançar o daemon do Docker do host (seção 5.3). | Sim |
| **sandbox** | Imagem dos containers efêmeros criados pelo `worker`. É só construída, nunca sobe como serviço. | Não (perfil `build`) |
| **frontend** | Tarefa que compila o SPA e copia o resultado para o volume servido pelo gateway. Termina logo após a cópia. | Sim, e encerra |
| **gateway** (Caddy) | Ponto de entrada HTTPS do ambiente publicado (staging). Localmente não é usado para acessar a aplicação. | Sim |
| **alloy** (Grafana Alloy) | Coleta logs e métricas e envia ao Grafana Cloud. Localmente só funciona se as credenciais do Grafana Cloud forem preenchidas. | Sim |

No ambiente local, o frontend é executado pelo servidor de desenvolvimento do Vite em `http://localhost:5173` (seção 8). O cliente `synapse-frontend` do Keycloak só aceita retorno de login para `http://localhost:5173` e para a URL de staging, por isso o bundle servido pelo gateway não serve para login local.

Os datasets históricos usados nas simulações já vão dentro da imagem do `worker`; não há passo de carga de dados.

---

## 2. Requisitos de máquina

### 2.1. Hardware

| Recurso | Mínimo | Recomendado |
| :--- | :--- | :--- |
| Memória disponível para o Docker | 4 GB | 8 GB |
| CPU | 2 núcleos | 4 núcleos ou mais |
| Disco livre | 10 GB | 20 GB |
| Arquitetura | x86_64 (amd64) ou ARM64 (Apple Silicon, por exemplo) | — |

Com tudo em execução, os containers usam cerca de 1 GB de memória. O pico acontece no build da imagem da `api`, que compila o projeto Maven dentro do Docker. No Windows e no macOS, a memória disponível para o Docker é configurada no Docker Desktop (seções 3.2 e 3.3).

### 2.2. Software

| Software | Versão | Para quê | Obrigatório? |
| :--- | :--- | :--- | :---: |
| Git | qualquer recente | Clonar o repositório | Sim |
| Docker Engine (Linux) ou Docker Desktop (Windows/macOS) | Engine `24.0.0` ou superior | Executar os containers | Sim |
| Docker Compose | `v2.20.0` ou superior | Orquestrar os serviços | Sim |
| Node.js | `22.18.0` ou superior na linha 22, ou `24.12.0` ou superior | Executar o frontend com Vite | Sim, para usar a aplicação pelo navegador |
| Python | `3.10` ou superior | Executar o script de dados de demonstração (seed) e o script de configuração do Keycloak | Opcional |

Java, Maven e PostgreSQL **não** precisam estar instalados na máquina: a `api` é compilada dentro do Docker e o banco roda em container.

Contas e chaves externas:

| Chave | Onde vai | Sem ela |
| :--- | :--- | :--- |
| `GOOGLE_API_KEY` (Gemini) | `codegen/.env` | O `codegen` sobe, mas toda geração de regra falha. |
| `DEEPGRAM_API_KEY` | `deploy/.env` | A `api` sobe e recusa a entrada por voz. A entrada por texto continua funcionando. |
| Credenciais do Grafana Cloud | `deploy/.env` (`GCLOUD_*`) | O `alloy` sobe, mas não entrega logs nem métricas. Não afeta a aplicação. |

Peça as chaves ao time por canal privado. Nunca as coloque em arquivos versionados.

---

## 3. Preparar o sistema operacional

Escolha a seção do seu sistema. Ao final dela, os comandos abaixo devem funcionar no terminal:

```bash
git --version
docker --version
docker compose version
docker run --rm hello-world
node --version
```

### 3.1. Linux

As instruções usam o Docker Engine nativo, que roda como root (modo padrão). O Docker Desktop para Linux também funciona, mas não é necessário.

#### Ubuntu e Debian

Instale pelo repositório oficial do Docker. O pacote `docker.io` das distribuições pode vir sem o plugin `docker compose` v2.

```bash
# Remove pacotes antigos que conflitam (pode avisar que nada foi encontrado)
sudo apt remove -y docker.io docker-doc docker-compose podman-docker containerd runc

# Repositório oficial
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Docker Engine, Buildx e Compose v2
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

No **Debian**, troque `ubuntu` por `debian` nas duas URLs. Para outras variantes, siga o [guia oficial de instalação](https://docs.docker.com/engine/install/).

#### Fedora

```bash
sudo dnf -y install dnf-plugins-core git
sudo dnf config-manager addrepo --from-repofile=https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

#### Arch Linux e derivadas

```bash
sudo pacman -S --needed docker docker-compose docker-buildx git
```

#### Depois de instalar, em qualquer distribuição

1. Ative o serviço e faça-o subir junto com o sistema:

   ```bash
   sudo systemctl enable --now docker
   ```

2. Permita usar o Docker sem `sudo`, adicionando seu usuário ao grupo `docker`:

   ```bash
   sudo usermod -aG docker "$USER"
   ```

   Encerre a sessão e entre de novo (ou reinicie) para o grupo valer. Para usar no terminal atual sem sair, execute `newgrp docker`.

3. Confirme: `docker run --rm hello-world` deve imprimir `Hello from Docker!` sem pedir senha.

#### Node.js no Linux

Os pacotes das distribuições costumam trazer versões antigas. Use o [nvm](https://github.com/nvm-sh/nvm):

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
# Feche e abra o terminal, depois:
nvm install 24
node --version   # deve ser 24.12.0 ou superior
```

#### Python no Linux (opcional)

A maioria das distribuições já traz Python 3.10 ou superior (`python3 --version`). No Ubuntu/Debian, instale também o módulo de ambientes virtuais: `sudo apt install -y python3-venv python3-pip`.

#### Docker rootless e Podman

O Compose do projeto monta o socket em `/var/run/docker.sock`, caminho do Docker em modo padrão. O Docker em modo *rootless* usa outro caminho (`$XDG_RUNTIME_DIR/docker.sock`) e o Podman tem outro daemon; nenhum dos dois funciona com o Compose atual sem alterar o arquivo. Use o Docker Engine em modo padrão.

### 3.2. Windows

O Docker no Windows roda containers Linux dentro do WSL 2 (Subsistema do Windows para Linux). Requisitos: Windows 10 versão 22H2 (build 19045) ou superior, ou Windows 11, com virtualização habilitada na BIOS/UEFI (Intel VT-x ou AMD-V).

#### Passo 1: instalar o WSL 2

Abra o **PowerShell como Administrador** e execute:

```powershell
wsl --install
```

O comando habilita os recursos necessários e instala o Ubuntu. Reinicie o computador quando pedido. Na primeira abertura do **Ubuntu** pelo menu Iniciar, crie um usuário e uma senha do Linux (não precisam ser iguais aos do Windows).

Confirme que a versão é 2:

```powershell
wsl --status
wsl -l -v
```

Se a distribuição aparecer com `VERSION 1`, converta com `wsl --set-version Ubuntu 2`.

#### Passo 2: instalar o Docker Desktop

1. Baixe o instalador em [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) ou instale pelo terminal: `winget install -e --id Docker.DockerDesktop`.
2. Durante a instalação, mantenha marcada a opção **Use WSL 2 instead of Hyper-V**.
3. Abra o Docker Desktop e aguarde o indicador **Engine running** no canto inferior esquerdo.
4. Em **Settings → General**, confirme que **Use the WSL 2 based engine** está marcado.
5. Em **Settings → Resources → WSL Integration**, ative a integração com a distribuição **Ubuntu** e clique em **Apply & restart**.
6. Confirme que o Docker está em modo **containers Linux**: clicando com o botão direito no ícone da baleia na bandeja, a opção exibida deve ser **Switch to Windows containers...** (se aparecer *Switch to Linux containers...*, clique nela).

O Docker Desktop precisa estar aberto sempre que você for usar o ambiente.

#### Passo 3: ajustar a memória do WSL (recomendado)

Por padrão, o WSL 2 usa até metade da memória do Windows. Se a máquina tem 8 GB ou menos, ou se o build da `api` falhar por falta de memória, crie o arquivo `%UserProfile%\.wslconfig` (por exemplo, `C:\Users\seu-usuario\.wslconfig`) com:

```ini
[wsl2]
memory=8GB
processors=4
```

Depois, no PowerShell, execute `wsl --shutdown` e abra o Docker Desktop de novo.

#### Passo 4: escolher onde executar os comandos

Há duas formas de trabalhar. Escolha uma e use-a em todo o manual.

| | **Opção A: terminal do Ubuntu (WSL)** — recomendada | **Opção B: PowerShell no Windows** |
| :--- | :--- | :--- |
| Onde fica o código | No sistema de arquivos do Linux, por exemplo `~/projects/synapse` | Numa pasta do Windows, por exemplo `C:\projects\synapse` |
| Comandos | Exatamente os de Linux deste manual | As variantes de PowerShell indicadas em cada seção e na seção 14 |
| Desempenho do build | Melhor: o Docker lê os arquivos sem atravessar a fronteira Windows/Linux | Mais lento, sobretudo no primeiro build |
| Editar os arquivos | Pelo VS Code com a extensão **WSL** (`code .` no terminal do Ubuntu) ou pelo Explorer em `\\wsl$\Ubuntu\home\<usuário>` | Qualquer editor do Windows |

Na opção A, instale as ferramentas dentro do Ubuntu, como num Linux comum: `sudo apt update && sudo apt install -y git python3-venv python3-pip`, e o Node.js pelo `nvm` (seção 3.1). Não instale o Docker Engine dentro do Ubuntu: o comando `docker` já vem do Docker Desktop pela integração do passo 2.

Na opção B, instale pelo PowerShell:

```powershell
winget install -e --id Git.Git
winget install -e --id OpenJS.NodeJS.LTS
winget install -e --id Python.Python.3.12
```

Feche e abra o PowerShell depois das instalações para o `PATH` ser atualizado. No Windows, o Python é chamado de `python` ou, pelo lançador, `py -3`; o alias `python3` da Microsoft Store não é necessário.

Duas diferenças do PowerShell que aparecem ao longo do manual:

- No Windows PowerShell 5.1, `curl` é um apelido de `Invoke-WebRequest` e não aceita as opções do curl. Use sempre `curl.exe`.
- Comandos longos não se quebram com `\`. Escreva-os numa linha só, ou quebre com o acento grave `` ` `` no fim da linha.

### 3.3. macOS

Funciona em Macs com Apple Silicon (M1 ou superior) e com Intel. Todas as imagens usadas pelo projeto têm versão nativa ARM64.

#### Passo 1: ferramentas de linha de comando e Homebrew

```bash
xcode-select --install          # instala o git e as ferramentas de compilação
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Siga as instruções que o instalador do Homebrew imprime no final para adicioná-lo ao `PATH` (no Apple Silicon, ele fica em `/opt/homebrew`).

#### Passo 2: instalar o Docker Desktop

```bash
brew install --cask docker
```

Ou baixe o `.dmg` em [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/), escolhendo **Apple Silicon** ou **Intel** conforme o seu Mac ( → Sobre Este Mac).

1. Abra o **Docker** em Aplicativos e aceite os termos e a permissão de privilégio pedida na primeira execução.
2. Em **Settings → Resources**, reserve pelo menos 4 GB de memória (8 GB recomendado) e 4 CPUs.
3. Aguarde o indicador **Engine running**.

Alternativas ao Docker Desktop, como [OrbStack](https://orbstack.dev/) e [Colima](https://github.com/abiosoft/colima), também expõem o socket padrão aos containers. Com Colima, reserve recursos ao iniciar: `colima start --cpu 4 --memory 8`.

#### Passo 3: Node.js e Python

```bash
brew install node@24 python@3.12
echo 'export PATH="$(brew --prefix node@24)/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
node --version   # deve ser 24.12.0 ou superior
```

No macOS, use `python3` nos comandos deste manual.

---

## 4. Obter o código

Linux, macOS ou Windows com WSL (opção A):

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/Titus-System/synapse.git
cd synapse
git switch develop
```

Windows com PowerShell (opção B):

```powershell
mkdir C:\projects -Force; cd C:\projects
git clone https://github.com/Titus-System/synapse.git
cd synapse
git switch develop
```

Todos os comandos a seguir são executados **na raiz do repositório** (a pasta `synapse`), salvo indicação contrária.

O repositório força finais de linha `LF` pelo `.gitattributes`. Isso importa no Windows: scripts `.sh` com finais `CRLF` quebram a inicialização do banco e dos containers (seção 13). Não altere essa configuração.

---

## 5. Configurar as variáveis de ambiente

São dois arquivos, nenhum deles versionado:

| Arquivo | Criado a partir de | Conteúdo |
| :--- | :--- | :--- |
| `deploy/.env` | `deploy/.env.example` | Senhas, portas, Keycloak, `DOCKER_GID` e chave da Deepgram. Obrigatório. |
| `codegen/.env` | `codegen/.env.example` | Chave do Gemini (`GOOGLE_API_KEY`). Opcional para subir, necessário para gerar regras. |

### 5.1. Criar `deploy/.env`

Linux, macOS ou WSL:

```bash
cp deploy/.env.example deploy/.env
```

PowerShell:

```powershell
Copy-Item deploy\.env.example deploy\.env
```

Abra `deploy/.env` num editor e ajuste os valores abaixo. Os demais podem ficar como no exemplo.

| Variável | O que colocar | Observação |
| :--- | :--- | :--- |
| `SYNAPSE_API_DB_PASSWORD` | Uma senha qualquer, sem espaços | Senha do usuário de banco da `api`. |
| `SYNAPSE_CODEGEN_DB_PASSWORD` | Uma senha qualquer, sem espaços | Senha do usuário de banco do `codegen`. |
| `SYNAPSE_WORKER_DB_PASSWORD` | Uma senha qualquer, sem espaços | Senha do usuário de banco do `worker`. |
| `KEYCLOAK_ADMIN_PASSWORD` | Uma senha qualquer | Senha do administrador do console do Keycloak. |
| `DOCKER_GID` | O número obtido na seção 5.3 | Varia por máquina; não copie o de outra pessoa. |
| `POSTGRES_PORT` | `5432`, ou `5433` se já houver um PostgreSQL na máquina | Porta do banco **no host**. Dentro da rede Docker ela é sempre `5432`. |
| `DEEPGRAM_API_KEY` | A chave da Deepgram, se tiver | Só para a entrada por voz. |

As senhas dos usuários de banco são gravadas **somente na primeira subida** do PostgreSQL, quando o volume de dados ainda está vazio. Mudá-las depois no `.env` não altera o banco: veja a seção 13.

O Compose exige `SYNAPSE_*_DB_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD` e `DOCKER_GID` em qualquer comando, até nos que selecionam um único serviço. Se faltar alguma, o comando para com a mensagem `defina em deploy/.env`.

### 5.2. Criar `codegen/.env`

Linux, macOS ou WSL:

```bash
cp codegen/.env.example codegen/.env
```

PowerShell:

```powershell
Copy-Item codegen\.env.example codegen\.env
```

Preencha `GOOGLE_API_KEY=` com a chave do Gemini. As variáveis de banco e RabbitMQ desse arquivo não precisam ser alteradas: no Compose, o `codegen` recebe os endereços da rede Docker e a senha de `deploy/.env`, que prevalecem sobre este arquivo.

### 5.3. `DOCKER_GID`: acesso do `worker` ao daemon do Docker

O `worker` é o único componente que executa código gerado por IA, e o faz subindo um container efêmero por execução. Para isso ele recebe o socket do Docker do host montado dentro do próprio container:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

O container do `worker` roda como usuário sem privilégios (`appuser`, uid 1000). Para usar o socket, ele precisa pertencer ao grupo dono do arquivo, e o Compose o adiciona a esse grupo pelo número em `DOCKER_GID`. Com o número errado, o processo enxerga o socket mas recebe *permission denied* e o `worker` não sobe.

O comando abaixo mostra o número **exatamente como os containers o enxergam** e funciona igual em Linux, macOS e Windows (PowerShell ou WSL), com o Docker já em execução:

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock alpine:3.20 stat -c '%g' /var/run/docker.sock
```

Coloque o número impresso em `deploy/.env`:

```dotenv
DOCKER_GID=984   # troque pelo número que o comando acima devolveu
```

Valores típicos, apenas para conferência:

| Sistema | Valor típico | Conferência alternativa |
| :--- | :--- | :--- |
| Linux (Docker Engine) | Varia por distribuição (por exemplo, `999`, `984`, `998`) | `getent group docker \| cut -d: -f3` |
| Windows (Docker Desktop) | `0` | — |
| macOS (Docker Desktop) | `0` | — |

Se o valor do comando divergir da tabela, vale o do comando.

> **Nota de segurança:** montar o socket dá ao `worker` controle sobre o daemon do host, o que equivale a acesso root na máquina. É uma consequência aceita do desenho: o `worker` existe para conter código não confiável em containers descartáveis, e quem cria esses containers precisa falar com o daemon. O código gerado nunca roda no processo do `worker`, apenas dentro do container efêmero, que não tem rede nem acesso ao socket.

---

## 6. Construir as imagens

### 6.1. Imagem do sandbox (obrigatória antes do primeiro uso)

O `worker` executa cada job num container criado a partir da imagem `synapse-sandbox:local`. Essa imagem não sobe com o `up`: ela só é construída. Construa-a uma vez e de novo sempre que `worker/sandbox/` mudar. Sem ela, o `worker` sobe normalmente, mas todo comando de execução falha e acaba na fila de mensagens mortas (DLQ).

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml --profile build build sandbox
```

No Linux e no macOS, com `make` instalado, o atalho equivalente é `make build-sandbox-image`.

### 6.2. Imagens dos serviços

As imagens de `api`, `codegen`, `worker` e `frontend` são construídas a partir do código local. O primeiro build baixa as imagens base e as dependências (Maven, pip, npm) e pode levar vários minutos; os seguintes reaproveitam o cache.

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml build
```

Esse passo é opcional: o `up --build` da seção 7 constrói o que faltar. Rodá-lo separado ajuda a ver erros de build antes de subir os serviços.

---

## 7. Subir os serviços

### 7.1. Subir o ambiente completo

A partir da raiz do repositório:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build --wait
```

- `-d` libera o terminal e deixa os containers em segundo plano.
- `--build` reconstrói as imagens cujo código mudou.
- `--wait` só devolve o terminal quando os serviços com *healthcheck* estiverem saudáveis. A `api` costuma ser a última, pois aplica as migrations ao iniciar.

Também é possível executar a partir de `deploy/`, onde o Compose encontra o `.env` sozinho:

```bash
cd deploy
docker compose up -d --build --wait
```

No Linux e no macOS, `make up-build` constrói o sandbox e sobe tudo de uma vez.

Na primeira subida, o PostgreSQL cria o banco `synapse_db` e os usuários `synapse_api`, `synapse_codegen` e `synapse_worker`; o Keycloak importa o realm `synapse`; a `api` aplica as migrations e concede as permissões de cada serviço.

### 7.2. Subir só o necessário

O `gateway` e o `alloy` não são necessários para usar a aplicação localmente. Para deixá-los de fora (útil com pouca memória, ou se as portas 80 e 443 estiverem ocupadas), liste os serviços desejados:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build --wait postgres rabbitmq keycloak api codegen worker
```

As dependências entre serviços são respeitadas: por exemplo, a `api` só inicia depois de o PostgreSQL e o RabbitMQ estarem saudáveis.

Sobre os dois serviços opcionais:

- O **gateway** usa as portas 80 e 443 do host e está configurado para os domínios de staging. Localmente ele tenta emitir certificados para esses domínios e registra falhas no log; isso não afeta os outros serviços.
- O **alloy** envia logs e métricas ao Grafana Cloud. Com as credenciais de exemplo, ele sobe e registra erros de envio; isso não afeta os outros serviços.

---

## 8. Executar o frontend

O frontend é executado pelo Vite, fora do Docker. O Vite encaminha as chamadas `/api` para a `api` em `http://localhost:8080`.

1. Crie `frontend/.env` a partir do exemplo (os valores padrão servem para o ambiente local):

   ```bash
   cp frontend/.env.example frontend/.env              # Linux, macOS, WSL
   ```

   ```powershell
   Copy-Item frontend\.env.example frontend\.env       # PowerShell
   ```

   O conteúdo esperado é:

   ```dotenv
   VITE_API_BASE_URL=/api
   VITE_KEYCLOAK_URL=http://localhost:8081
   VITE_KEYCLOAK_REALM=synapse
   VITE_KEYCLOAK_CLIENT_ID=synapse-frontend
   ```

2. Instale as dependências e inicie o servidor de desenvolvimento:

   ```bash
   cd frontend
   npm ci
   npm run dev
   ```

3. Acesse **`http://localhost:5173`**. O navegador é redirecionado para o login do Keycloak.

Use exatamente `localhost`, e não `127.0.0.1`: o emissor do token, os cookies e as URLs de retorno do Keycloak foram configurados para `localhost`.

O terminal do `npm run dev` precisa ficar aberto enquanto você usa a aplicação. Para parar, pressione `Ctrl+C`.

---

## 9. Criar um usuário de acesso

O realm `synapse` vem sem usuários. Há duas formas de criar contas: pelo console do Keycloak ou pelo script de dados de demonstração.

### 9.1. Pelo console do Keycloak

1. Acesse `http://localhost:8081/admin/` e entre com `KEYCLOAK_ADMIN_USERNAME` (padrão `admin`) e `KEYCLOAK_ADMIN_PASSWORD` de `deploy/.env`.
2. No seletor de realm, no canto superior esquerdo, escolha **synapse**. Não crie contas da aplicação no realm `master`.
3. Vá em **Users → Add user**. Preencha **Username** e **Email** com o mesmo endereço (por exemplo `rh@example.test`) e **First name**. Ative **Email verified**: o realm exige e-mail verificado e o ambiente local não envia e-mails. Clique em **Create**.
4. Na aba **Credentials**, clique em **Set password**, defina uma senha e desmarque **Temporary**.
5. Na aba **Role mapping**, clique em **Assign role**, filtre por papéis do realm e atribua **exatamente um** papel de negócio:
   - `profissional-rh`: cria e acompanha simulações;
   - `auditor`: consulta a auditoria e recebe `403` nas rotas de jobs.
6. Entre em `http://localhost:5173` com o e-mail e a senha criados.

Na primeira chamada à `api`, a conta é registrada localmente na tabela `usuarios`. Uma conta com os dois papéis, ou com nenhum, é recusada.

### 9.2. Pelo script de dados de demonstração (seed)

O script `deploy/scripts/seed.py` cria três contas no Keycloak (`develop@synapse.pro` com `profissional-rh`, `staging@synapse.pro` e `auditor@synapse.pro` com `auditor`) e jobs de demonstração no banco. Ele redefine a senha dessas três contas a cada execução. Os detalhes estão no [guia do Keycloak](../deploy/keycloak/README.md#dados-de-demonstração).

Pré-requisitos: Python 3.10 ou superior, e os serviços `postgres`, `keycloak` e `api` saudáveis (o script confere se as migrations foram aplicadas).

O script lê variáveis de ambiente, não o arquivo `deploy/.env`. Exporte-as com os mesmos valores do seu `deploy/.env`. `SEED_USERS_PASSWORD` é a senha que as três contas de demonstração vão receber.

Linux, macOS ou WSL:

```bash
python3 -m venv deploy/scripts/venv
source deploy/scripts/venv/bin/activate
python -m pip install -r deploy/scripts/requirements.txt

export POSTGRES_PORT=5432                  # o valor de POSTGRES_PORT em deploy/.env
export POSTGRES_PASSWORD=postgres          # o valor de POSTGRES_PASSWORD em deploy/.env
export KEYCLOAK_ADMIN_PASSWORD='...'       # o valor de KEYCLOAK_ADMIN_PASSWORD em deploy/.env
export SEED_USERS_PASSWORD='...'           # escolha uma senha para as contas de demonstração

python deploy/scripts/seed.py
```

PowerShell:

```powershell
py -3 -m venv deploy\scripts\venv
.\deploy\scripts\venv\Scripts\Activate.ps1
python -m pip install -r deploy\scripts\requirements.txt

$env:POSTGRES_PORT = "5432"
$env:POSTGRES_PASSWORD = "postgres"
$env:KEYCLOAK_ADMIN_PASSWORD = "..."
$env:SEED_USERS_PASSWORD = "..."

python deploy\scripts\seed.py
```

Se o PowerShell recusar o `Activate.ps1` por política de execução, libere-a para o usuário atual com `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de novo.

Se o seu `deploy/.env` mudou outros valores padrão, exporte também `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `KEYCLOAK_PUBLIC_URL` e `KEYCLOAK_ADMIN_USERNAME`.

---

## 10. Verificar a instalação

### 10.1. Estado dos containers

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
```

Saída esperada (colunas resumidas; as portas mostradas refletem os valores de `deploy/.env`):

```text
NAME                      IMAGE                              STATUS                PORTS
synapse-alloy             grafana/alloy:latest               Up                    
synapse-gateway           caddy:2-alpine                     Up (healthy)          0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
synapse-infra-api-1       synapse-api:local                  Up (healthy)          0.0.0.0:8080->8080/tcp
synapse-infra-codegen-1   synapse-codegen:local              Up (healthy)          0.0.0.0:8001->8000/tcp
synapse-infra-worker-1    synapse-worker:local               Up (healthy)          0.0.0.0:8002->8000/tcp
synapse-keycloak          quay.io/keycloak/keycloak:26.7.4   Up (healthy)          127.0.0.1:8081->8080/tcp
synapse-postgres          postgres:18-alpine                 Up (healthy)          0.0.0.0:5432->5432/tcp
synapse-rabbitmq          rabbitmq:3.13-management-alpine    Up (healthy)          0.0.0.0:5672->5672/tcp, 0.0.0.0:15672->15672/tcp
```

O `frontend` do Compose não aparece: é uma tarefa de build e cópia que termina logo após concluir. Para vê-la, use `ps -a`; o estado esperado é `Exited (0)`. Logo após a subida, um serviço pode aparecer como `Up (health: starting)` por até um minuto antes de ficar `healthy`.

### 10.2. Testes por serviço

Nos blocos abaixo, o primeiro comando serve para Linux, macOS e WSL. No PowerShell, troque `curl` por `curl.exe`.

1. **PostgreSQL**

   ```bash
   docker exec synapse-postgres pg_isready -U postgres -d synapse_db
   # Retorno esperado: /var/run/postgresql:5432 - accepting connections
   ```

   O usuário `postgres` é o **dono do schema**: só as migrations da `api` o usam. Cada serviço conecta com um usuário próprio (`synapse_api`, `synapse_codegen`, `synapse_worker`), com a senha definida em `deploy/.env`. Para confirmar que os três existem:

   ```bash
   docker exec synapse-postgres psql -U postgres -d synapse_db -c "\du"
   ```

2. **RabbitMQ**: abra [http://localhost:15672](http://localhost:15672) e entre com `guest` / `guest` (ou os valores de `RABBITMQ_DEFAULT_USER` e `RABBITMQ_DEFAULT_PASS`). Com `api`, `codegen` e `worker` em execução, a aba **Queues and Streams** lista as filas declaradas, entre elas `executar-codigo`.

3. **Keycloak**

   ```bash
   curl --fail http://localhost:8081/realms/synapse/.well-known/openid-configuration
   ```

   O retorno é um JSON com `"issuer":"http://localhost:8081/realms/synapse"`. O console fica em [http://localhost:8081/admin/](http://localhost:8081/admin/). A porta do Keycloak é publicada só em `127.0.0.1`, portanto não é acessível por outras máquinas da rede.

4. **API**

   ```bash
   curl --fail http://localhost:8080/actuator/health
   # Retorno esperado: {"status":"UP"}
   ```

5. **codegen**

   ```bash
   curl --fail http://localhost:8001/health
   # Retorno esperado: {"status":"UP"}
   ```

6. **worker**

   ```bash
   curl --fail http://localhost:8002/health
   # Retorno esperado: "ok"
   ```

   O `worker` verifica o acesso ao daemon do Docker e declara a fila durante a subida. Os dois ficam registrados no log:

   ```bash
   docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs worker | grep -E "daemon|fila"
   ```

   No PowerShell, troque `grep -E "daemon|fila"` por `Select-String -Pattern "daemon|fila"`.

   ```json
   {"message":"acesso ao daemon do Docker verificado","extra":{"containers_em_execucao":5}}
   {"message":"fila de execução declarada","extra":{"fila":"executar-codigo","prefetch":1}}
   ```

   Se essas linhas não aparecem, o processo não subiu: confira a seção 13.

7. **Imagem do sandbox**

   ```bash
   docker image ls synapse-sandbox
   # Deve listar synapse-sandbox com a tag local
   ```

8. **Ponta a ponta**: entre em `http://localhost:5173` com um usuário `profissional-rh` (seção 9) e envie uma regra por texto. A simulação só conclui com `GOOGLE_API_KEY` preenchida em `codegen/.env`.

---

## 11. Tabela de serviços, portas e credenciais

Os nomes de host, portas e credenciais abaixo são os padrões do desenvolvimento local. Mantenha-os para não precisar ajustar a configuração dos serviços dependentes.

| Serviço | Nome do container | Hostname na rede `synapse-net` | Porta no host | Porta interna | Usuário | Senha | Banco / VHost | Acesso |
| :--- | :--- | :--- | :---: | :---: | :--- | :--- | :--- | :--- |
| **PostgreSQL** | `synapse-postgres` | `postgres` | `POSTGRES_PORT` (`5432` no exemplo) | `5432` | `postgres` | `postgres` | `synapse_db` | `postgresql://postgres:postgres@localhost:5432/synapse_db` |
| **RabbitMQ (AMQP)** | `synapse-rabbitmq` | `rabbitmq` | `5672` | `5672` | `guest` | `guest` | `/` | `amqp://guest:guest@localhost:5672` |
| **RabbitMQ (painel)** | `synapse-rabbitmq` | `rabbitmq` | `15672` | `15672` | `guest` | `guest` | — | [http://localhost:15672](http://localhost:15672) |
| **Keycloak** | `synapse-keycloak` | `keycloak` | `8081` (só `127.0.0.1`) | `8080` | `KEYCLOAK_ADMIN_USERNAME` | `KEYCLOAK_ADMIN_PASSWORD` | realm `synapse` | [http://localhost:8081/admin/](http://localhost:8081/admin/) |
| **API** | `synapse-infra-api-1` | `api` | `8080` | `8080` | — | — | — | [http://localhost:8080/actuator/health](http://localhost:8080/actuator/health) |
| **codegen** | `synapse-infra-codegen-1` | `codegen` | `8001` | `8000` | — | — | — | [http://localhost:8001/health](http://localhost:8001/health) |
| **worker** | `synapse-infra-worker-1` | `worker` | `8002` | `8000` | — | — | — | [http://localhost:8002/health](http://localhost:8002/health) |
| **Frontend (Vite)** | — (fora do Docker) | — | `5173` | — | usuário do realm `synapse` | — | — | [http://localhost:5173](http://localhost:5173) |
| **Gateway** | `synapse-gateway` | `gateway` | `80`, `443` | `80`, `443` | — | — | — | Usado só no ambiente publicado |

Usuários de banco por serviço: `synapse_api`, `synapse_codegen` e `synapse_worker`, com as senhas de `deploy/.env`.

Todas as portas no host podem ser trocadas em `deploy/.env` (`POSTGRES_PORT`, `RABBITMQ_PORT`, `RABBITMQ_MANAGEMENT_PORT`, `KEYCLOAK_PORT`, `API_PORT`, `CODEGEN_PORT`, `WORKER_PORT`, `HTTP_PORT`, `HTTPS_PORT`). Duas exigem ajustes adicionais:

- `API_PORT`: o proxy do Vite em `frontend/vite.config.ts` aponta para `http://localhost:8080`.
- `KEYCLOAK_PORT`: ajuste também `KEYCLOAK_PUBLIC_URL` e `KEYCLOAK_ISSUER_URI` em `deploy/.env` e `VITE_KEYCLOAK_URL` em `frontend/.env`. As três precisam usar a mesma origem.

As demais variáveis estão comentadas em `deploy/.env.example`.

---

## 12. Ciclo de vida e persistência de dados

Todos os comandos abaixo valem para Linux, macOS, WSL e PowerShell.

### Parar os serviços preservando os dados

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down
```

Os volumes nomeados preservam os dados do PostgreSQL (`synapse-postgres-data`), do RabbitMQ (`synapse-rabbitmq-data`) e do Keycloak (`synapse-infra_keycloak-data`). Ao subir de novo, os volumes são reutilizados, incluindo usuários e realm do Keycloak.

No Windows e no macOS, fechar o Docker Desktop também para os containers. Ao reabri-lo, os serviços com `restart: unless-stopped` voltam sozinhos.

### Reiniciar os serviços

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml restart
```

`restart` não relê o `deploy/.env`. Depois de alterar uma variável, recrie o serviço afetado:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --force-recreate api
```

### Aplicar mudanças de código

Depois de atualizar o repositório (`git pull`) ou alterar o código de um serviço, reconstrua e recrie só o que mudou:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build --wait api codegen worker
```

Se `worker/sandbox/` mudou, reconstrua também a imagem do sandbox (seção 6.1). Se `frontend/package.json` mudou, rode `npm ci` de novo em `frontend/`.

### Consultar logs

```bash
# Todos os serviços, acompanhando em tempo real
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs -f

# Um serviço, últimas 100 linhas
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs --tail 100 api
```

Troque `api` por `postgres`, `rabbitmq`, `keycloak`, `codegen` ou `worker`. Para sair do modo `-f`, pressione `Ctrl+C`; os containers continuam em execução.

### Resetar o ambiente (destruição total de dados)

Para recriar banco, filas e configuração do Keycloak do zero, apagando também usuários, realm e sessões:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down -v
```

Na próxima subida, o PostgreSQL recria os usuários de banco com as senhas atuais do `deploy/.env` e o Keycloak reimporta o realm. Os usuários criados na seção 9 precisam ser criados de novo.

### Liberar espaço em disco

Builds repetidos acumulam camadas de cache. Para remover o cache de build e imagens sem uso (os volumes de dados não são afetados):

```bash
docker builder prune
docker image prune
```

---

## 13. Resolução de problemas

### O comando para com `defina em deploy/.env`

Falta uma variável obrigatória em `deploy/.env`: `SYNAPSE_API_DB_PASSWORD`, `SYNAPSE_CODEGEN_DB_PASSWORD`, `SYNAPSE_WORKER_DB_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD` ou `DOCKER_GID`. A mensagem indica qual. Se aparecer `ver docs/instalacao.md`, é `DOCKER_GID`: volte à seção 5.3.

Se a mensagem for `couldn't find env file`, o comando foi executado fora da raiz do repositório ou `deploy/.env` não foi criado (seção 5.1).

### `Cannot connect to the Docker daemon` ou `docker: command not found`

- **Linux:** confirme que o serviço está ativo (`sudo systemctl status docker`) e que seu usuário está no grupo `docker` (`groups` deve listar `docker`). Se acabou de rodar `usermod`, encerre a sessão e entre de novo.
- **Windows:** abra o Docker Desktop e aguarde **Engine running**. No terminal do Ubuntu, se `docker` não existir, ative a integração em **Settings → Resources → WSL Integration** e reabra o terminal.
- **macOS:** abra o Docker Desktop e aguarde **Engine running**. Com Colima, execute `colima start`.

### Porta já em uso (`bind: address already in use` ou `ports are not available`)

Outro programa já usa a porta. Os casos mais comuns são PostgreSQL (5432), RabbitMQ (5672/15672), outro servidor web (80/443) ou uma instância antiga do Synapse.

Descubra quem usa a porta:

```bash
# Linux
sudo ss -ltnp | grep ':5432'
# macOS
lsof -nP -iTCP:5432 -sTCP:LISTEN
```

```powershell
# Windows
Get-NetTCPConnection -LocalPort 5432 -State Listen | Select-Object OwningProcess
Get-Process -Id <número do OwningProcess>
```

Soluções: pare o serviço local (por exemplo, `sudo systemctl stop postgresql` no Linux, `brew services stop postgresql` no macOS, ou o serviço `postgresql-x64-*` em `services.msc` no Windows), mude a porta em `deploy/.env` (seção 11) ou, para 80/443, suba sem o gateway (seção 7.2).

No Windows, o Hyper-V e o WSL reservam faixas de portas que mudam a cada reinicialização. Se a porta não aparece em uso mas o erro persiste, confira com `netsh interface ipv4 show excludedportrange protocol=tcp` e escolha outra porta fora das faixas listadas.

### O `worker` não sobe: sem acesso ao daemon do Docker

Se o container do `worker` sobe e morre em seguida, ou fica reiniciando, o log traz a causa:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs --tail 20 worker
```

```text
DaemonIndisponivelError: sem acesso ao daemon do Docker em unix:///var/run/docker.sock
```

O `worker` encerra o processo de propósito nesse caso, em vez de subir e falhar só na primeira execução. Causas prováveis, em ordem:

1. **`DOCKER_GID` com o número errado.** É o caso mais comum, porque o número muda de máquina para máquina. Obtenha-o de novo com o comando da seção 5.3 e recrie o container (`docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --force-recreate worker`). Mudar o `.env` sem recriar não basta.
2. **Docker rootless ou Podman (Linux).** O socket fica em outro caminho e o Compose atual não o encontra. Use o Docker Engine em modo padrão (seção 3.1).
3. **Daemon parado no host.** Confirme com `docker info` na sua máquina, fora do Compose.

### Jobs vão para a DLQ e o log do `worker` cita a imagem do sandbox

A imagem `synapse-sandbox:local` não existe ou está desatualizada. Construa-a (seção 6.1). Não é preciso reiniciar o `worker`.

### Container não sobe: `$'\r': command not found`, `bad interpreter` ou `no such file or directory` no `entrypoint.sh`

Um script `.sh` foi gravado com finais de linha do Windows (`CRLF`), em geral por um editor do Windows. Os mais sensíveis são `deploy/postgres/initdb/010-usuarios-de-banco.sh` (PostgreSQL) e os `entrypoint.sh` de `codegen` e `worker`. Liste os arquivos afetados na raiz do repositório:

```bash
git ls-files --eol | grep "w/crlf"
```

Para cada arquivo listado, apague a cópia local e restaure a versão do repositório, que vem com `LF`. Isso descarta alterações locais **somente nesse arquivo**:

```bash
rm deploy/postgres/initdb/010-usuarios-de-banco.sh
git restore deploy/postgres/initdb/010-usuarios-de-banco.sh
```

No PowerShell, troque `rm` por `Remove-Item` e `grep "w/crlf"` por `Select-String "w/crlf"`. Se o arquivo corrigido for um `entrypoint.sh`, reconstrua a imagem do serviço (`up -d --build`). Se for o script do PostgreSQL, apague o volume do banco, que ficou incompleto, e suba de novo:

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down -v
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build --wait
```

### `api`, `codegen` ou `worker` não conectam ao banco (`password authentication failed`)

As senhas dos usuários de banco são gravadas só na primeira subida, com o volume vazio. Se você mudou `SYNAPSE_*_DB_PASSWORD` em `deploy/.env` depois disso, o banco continua com a senha antiga. Há duas saídas:

- Ambiente descartável: `down -v` e subir de novo (seção 12). Apaga todos os dados.
- Preservando os dados: atualize a senha no banco e recrie o serviço. Exemplo para a `api`:

  ```bash
  docker exec -it synapse-postgres psql -U postgres -d synapse_db -c "ALTER ROLE synapse_api PASSWORD 'nova-senha';"
  docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --force-recreate api
  ```

Se o log do PostgreSQL mostrar `initdb: senha vazia para ...`, a senha correspondente está vazia em `deploy/.env`. Preencha-a e repita com `down -v`.

### O build da `api` falha ou trava (`exit code: 137`, `killed`)

O Docker ficou sem memória durante a compilação. Aumente a memória do Docker (Windows: `.wslconfig`, seção 3.2; macOS: **Settings → Resources**, seção 3.3), pare outros containers e repita o build.

### Login falha, entra em loop ou mostra `Invalid redirect uri`

- Acesse o frontend por `http://localhost:5173`, não por `127.0.0.1` nem pelo IP da máquina.
- O Vite precisa estar na porta 5173. Se ela estiver ocupada, o Vite sobe em outra porta (por exemplo, 5174), que o Keycloak não aceita. Libere a 5173 e reinicie o `npm run dev`.
- Confira se `VITE_KEYCLOAK_URL` em `frontend/.env` é igual a `KEYCLOAK_PUBLIC_URL` em `deploy/.env`.
- O usuário precisa ter **Email verified** ativado e exatamente um papel de negócio (seção 9.1).

### A tela abre, mas as chamadas à API respondem `401` ou `403`

- `401`: o emissor do token não confere. `KEYCLOAK_ISSUER_URI` em `deploy/.env` precisa ser `http://localhost:8081/realms/synapse`. Depois de corrigir, recrie a `api`.
- `403` em todas as rotas de jobs: o usuário tem o papel `auditor`, que não acessa jobs. Use uma conta `profissional-rh`.

### A regra não é gerada e o job falha logo no início

Confira o log do `codegen`. A mensagem `GOOGLE_API_KEY is not configured` indica que `codegen/.env` não existe ou está sem a chave (seção 5.2). Depois de preencher, recrie o serviço: `docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --force-recreate codegen`. Respostas `429` do Gemini indicam limite de requisições da conta; aguarde um minuto e tente de novo.

### `npm ci` falha com `EBADENGINE` ou erro de sintaxe

A versão do Node.js é antiga. Instale a 24.12.0 ou superior (ou 22.18.0 ou superior na linha 22) e confira com `node --version`.

### O `alloy` ou o `gateway` registram erros no log

Localmente isso é esperado: o `alloy` não tem credenciais do Grafana Cloud e o `gateway` tenta emitir certificados para os domínios de staging. Nenhum dos dois afeta a aplicação. Para não subi-los, use a lista de serviços da seção 7.2.

### Ambiente de teste do cadastro e da recuperação de senha no Windows

Para testar apenas o cadastro, a verificação de e-mail e a recuperação de senha, há um ambiente separado, com caixa de e-mail local, iniciado por `python deploy/keycloak/local/iniciar.py`. Ele não usa `deploy/.env` nem sobe `codegen` e `worker`. O roteiro está em [`deploy/keycloak/local/README.md`](../deploy/keycloak/local/README.md).

---

## 14. Referência rápida de comandos por sistema

| Ação | Linux, macOS e WSL | PowerShell (Windows) |
| :--- | :--- | :--- |
| Copiar arquivo de exemplo | `cp deploy/.env.example deploy/.env` | `Copy-Item deploy\.env.example deploy\.env` |
| Descobrir `DOCKER_GID` | `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock alpine:3.20 stat -c '%g' /var/run/docker.sock` | O mesmo comando |
| Construir o sandbox | `docker compose --env-file deploy/.env -f deploy/docker-compose.yml --profile build build sandbox` | O mesmo comando |
| Subir tudo | `docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build --wait` | O mesmo comando |
| Ver estado | `docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps` | O mesmo comando |
| Testar a API | `curl --fail http://localhost:8080/actuator/health` | `curl.exe --fail http://localhost:8080/actuator/health` |
| Filtrar log | `... logs worker \| grep -E "daemon\|fila"` | `... logs worker \| Select-String -Pattern "daemon\|fila"` |
| Definir variável para o seed | `export SEED_USERS_PASSWORD='...'` | `$env:SEED_USERS_PASSWORD = "..."` |
| Ativar ambiente virtual Python | `source deploy/scripts/venv/bin/activate` | `.\deploy\scripts\venv\Scripts\Activate.ps1` |
| Chamar o Python | `python3` | `python` ou `py -3` |
| Parar preservando dados | `docker compose --env-file deploy/.env -f deploy/docker-compose.yml down` | O mesmo comando |
| Apagar tudo, inclusive dados | `docker compose --env-file deploy/.env -f deploy/docker-compose.yml down -v` | O mesmo comando |
