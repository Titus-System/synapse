# frontend

Frontend em Vue 3 do projeto, construído com Vite. Faz parte de uma arquitetura de microsserviços maior (documentada no repositório de arquitetura do projeto): conversa com o backend (Spring Boot) via REST e recebe atualizações em tempo real via SSE.

## Requisitos

Este projeto roda em **Node.js 24** (o campo `engines` do `package.json` aceita `^22.18.0 || >=24.12.0`, mas 24 LTS é a versão suportada aqui). Versões antigas — Node 18 e 20 em particular — falham na instalação ou no build.

Confira o que você tem instalado:

```sh
node -v   # esperado: v24.x
npm -v    # esperado: 11.x, já vem com o Node 24
```

Se o resultado for diferente de `v24.x`, instale ou troque para o Node 24 com uma das opções abaixo.

### Instalar ou atualizar para o Node 24

#### Opção 1 — nvm (recomendado, Linux/macOS)

```sh
# instale o nvm se ainda não tiver
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
# reabra o terminal, ou: source ~/.nvm/nvm.sh

nvm install 24
nvm use 24
nvm alias default 24   # torna a 24 o padrão em novos shells
```

#### Opção 2 — fnm (Linux/macOS/Windows)

```sh
fnm install 24
fnm use 24
fnm default 24
```

#### Opção 3 — gerenciador de pacotes do sistema

```sh
# Debian/Ubuntu (NodeSource)
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo -E bash -
sudo apt-get install -y nodejs

# macOS (Homebrew)
brew install node@24
brew link --overwrite --force node@24

# Windows (winget)
winget install OpenJS.NodeJS.LTS
```

#### Opção 4 — instalador oficial

Baixe o build LTS do Node 24 para sua plataforma em [nodejs.org/en/download](https://nodejs.org/en/download).

Depois de trocar de versão, confirme com `node -v` que aparece `v24.x`. Se você veio de uma major mais antiga, reinstale as dependências para que os módulos nativos batam com o novo runtime:

```sh
rm -rf node_modules
npm install
```

## Configuração do ambiente

```sh
cp .env.example .env
```

Só variáveis com prefixo `VITE_` chegam ao cliente — e todas elas ficam visíveis no bundle final. Nunca coloque um segredo aqui; chaves e tokens ficam no backend. As variáveis disponíveis estão documentadas em `.env.example` e tipadas em `env.d.ts`.

## Rodando o projeto

Com o Node 24 ativo (ver [Requisitos](#requisitos)):

```sh
npm install
```

### Desenvolvimento com hot-reload

```sh
npm run dev
```

### Build de produção (type-check + minificação)

```sh
npm run build
```

### Pré-visualizar o build de produção localmente

```sh
npm run preview
```

### Testes unitários ([Vitest](https://vitest.dev/))

```sh
npm run test:unit
```

### Lint ([ESLint](https://eslint.org/) + [oxlint](https://oxc.rs/docs/guide/usage/linter))

```sh
npm run lint
```

### Tudo de uma vez

`make check` roda type-check, lint e testes nessa ordem — é o que precisa passar antes de considerar algo pronto:

```sh
make check
```

Rode `make help` para ver todos os alvos disponíveis (`dev`, `build`, `preview`, `test`, `format`, `clean`, etc.).

## Rodando com Docker

A imagem faz build multi-stage (Node 24 compila, [Caddy](https://caddyserver.com/) serve os arquivos estáticos com HTTPS automático) — ver [Dockerfile](Dockerfile), [docker/Caddyfile](docker/Caddyfile) e [deploy/docker-compose.yml](../deploy/docker-compose.yml).

Execute a partir da raiz do monorepo:

```sh
docker compose -f deploy/docker-compose.yml up -d --build
```

Por padrão sobe em `https://localhost`. Como `localhost` não é um domínio público, o Caddy emite um certificado pela própria CA interna dele — o navegador vai marcar a conexão como "não segura", e isso é esperado em ambiente local, não é um bug.

Variáveis de ambiente úteis (via `.env` na raiz ou exportadas no shell antes do `docker compose up`):

| Variável | Efeito |
| --- | --- |
| `SITE_ADDRESS` | Domínio do site no Caddy. Em produção, aponte para o domínio real (ex.: `app.exemplo.com`) para ganhar HTTPS automático via Let's Encrypt. |
| `VITE_API_BASE_URL` | URL base da API, embutida no bundle em tempo de build (build arg do Docker). Aponte para a API de staging/produção. |
| `HTTP_PORT` / `HTTPS_PORT` | Portas do host mapeadas para 80/443 do container. Padrão: `80`/`443`. |

```sh
SITE_ADDRESS=app.exemplo.com VITE_API_BASE_URL=https://api.exemplo.com docker compose -f deploy/docker-compose.yml up -d --build
```

## Estrutura do projeto

O projeto é organizado por feature: cada domínio é uma pasta fechada em `src/features/<nome>/`, com uma forma interna fixa (`routes.ts`, `types.ts`, `views/`, `components/`, `composables/`, `stores/`, `services/`). O que é compartilhado fica na raiz de `src/`.

As convenções completas — onde criar cada tipo de arquivo, regras de import entre features, TypeScript, estilo — estão em [AGENTS.md](AGENTS.md). Antes de criar um arquivo novo, vale ler também [src/features/README.md](src/features/README.md).

## Git hooks

Um hook `pre-commit` do Husky roda `make pre-commit` (type-check + lint + test) antes de cada commit — ele se instala sozinho na primeira vez que você roda `npm install`, sem passo extra.

**Clientes gráficos de git** (incluindo o painel Source Control do VS Code) rodam o git em um shell mínimo que pula `.bashrc`/`.zshrc`; um version manager configurado lá nunca é carregado, e o commit roda com o `node` que estiver primeiro no `PATH` do sistema — geralmente um mais antigo, o que falha com um erro de baixo nível confuso em vez de um aviso claro de versão. O hook tenta contornar isso carregando o nvm/fnm diretamente (ver `.husky/pre-commit`), o que cobre o caminho padrão de instalação do nvm; se ainda assim você tomar um erro de versão do Node vindo de um cliente gráfico, commitar por um terminal normal dentro da pasta do projeto funciona, porque o profile do seu shell _é_ carregado ali.

## Como contribuir

Estratégia de branches (o documento de arquitetura e processo do projeto tem o fluxo completo):

- **`main`** — código de produção. Nenhum commit direto; só entra via Pull Request, revisado e aprovado por pelo menos uma pessoa.
- **`staging`** — testes de integração e validação antes de produção. Atualizada a partir da `dev`; depois de validada pela PO, é mesclada na `main`.
- **`dev`** e **`feature/<nome-da-feature>`** — branches de desenvolvimento.

Fluxo de trabalho:

1. Crie uma branch `feature/<nome-da-feature>` a partir da `dev`.
2. Desenvolva e rode `make check` antes de cada commit (o hook de pre-commit já bloqueia isso automaticamente).
3. Escreva as mensagens de commit seguindo [.agents/skills/commit-and-comments/SKILL.md](.agents/skills/commit-and-comments/SKILL.md) — Conventional Commits em português, uma mudança lógica por commit, trailer `Review: human` ou `Review: auto`.
4. Abra um Pull Request para `dev` (ou `staging`, conforme o fluxo da sprint) com descrição do que mudou e por quê.
5. Aguarde revisão de pelo menos uma pessoa antes do merge.

Antes de abrir o PR, confira:

- [ ] `make check` passa (type-check, lint, testes).
- [ ] O código segue a estrutura por feature descrita em [AGENTS.md](AGENTS.md) — nada de uma feature importando de outra, nada fora do lugar combinado.
- [ ] Mudanças ficam restritas ao escopo da tarefa (ver a seção "Stay in scope" em [AGENTS.md](AGENTS.md)).

## Configuração recomendada de IDE

[VS Code](https://code.visualstudio.com/) + [Vue (Official)](https://marketplace.visualstudio.com/items?itemName=Vue.volar) (e desative o Vetur).

## Configuração recomendada de navegador

- Navegadores baseados em Chromium (Chrome, Edge, Brave, etc.):
  - [Vue.js devtools](https://chromewebstore.google.com/detail/vuejs-devtools/nhdogjmejiglipccpnnnanhbledajbpd)
  - [Ative o Custom Object Formatter no Chrome DevTools](http://bit.ly/object-formatters)
- Firefox:
  - [Vue.js devtools](https://addons.mozilla.org/en-US/firefox/addon/vue-js-devtools/)
  - [Ative o Custom Object Formatter no Firefox DevTools](https://fxdx.dev/firefox-devtools-custom-object-formatters/)

## Suporte de tipos para imports de `.vue` no TS

TypeScript não entende informação de tipos de imports `.vue` por padrão, então usamos o `vue-tsc` no lugar da CLI `tsc` para checagem de tipos. No editor, o [Volar](https://marketplace.visualstudio.com/items?itemName=Vue.volar) é necessário para que o language service do TypeScript reconheça os tipos de `.vue`.

## Customizando a configuração

Ver [Vite Configuration Reference](https://vite.dev/config/).
