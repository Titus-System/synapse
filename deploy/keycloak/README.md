# Keycloak local

A partir da raiz do repositório, prepare `deploy/.env` conforme o
[manual de instalação](../../docs/instalacao.md). Defina
`KEYCLOAK_ADMIN_PASSWORD` e mantenha `KEYCLOAK_ENABLED=true` para validar o fluxo
autenticado. Suba a identidade local junto dos serviços necessários:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build keycloak postgres rabbitmq api
```

O console administrativo fica em `http://localhost:8081/admin/`. As credenciais do
administrador vêm de `KEYCLOAK_ADMIN_USERNAME` e `KEYCLOAK_ADMIN_PASSWORD` em
`deploy/.env`.

O import cria o realm `synapse` e o cliente público `synapse-frontend`. Para
criar uma conta manualmente, use **synapse → Users**; não crie contas de uso da
aplicação no realm `master`. O usuário autenticado recebe uma conta local na
primeira chamada à API.

## Dados de demonstração

O script `deploy/scripts/seed.py` cria `develop@synapse.pro` com o papel
`profissional-rh` e `staging@synapse.pro` com o papel `auditor` no Keycloak.
Também grava essas contas em `usuarios`, com `keycloak_sub` igual ao identificador
retornado pelo Keycloak e `senha_hash` nulo. Os quatro jobs de demonstração ficam
vinculados à conta de RH. Em uma nova execução, o script reutiliza as contas,
redefine a senha de ambas e corrige a posse dos jobs criados por versões antigas
do seed.

Com o Keycloak e o banco já iniciados e as migrations da API aplicadas, instale
a dependência do script e execute-o a partir da raiz:

```bash
python3 -m pip install -r deploy/scripts/requirements.txt
python3 deploy/scripts/seed.py
```

Antes de executar, exporte `POSTGRES_PORT`, `KEYCLOAK_ADMIN_PASSWORD`,
`SEED_USERS_PASSWORD` e `POSTGRES_PASSWORD`. A porta deve ser a publicada pelo
Compose no host (`5433` no ambiente local deste guia), pois o seed exige esse
valor e não usa a porta interna do container. Se seu `deploy/.env` usar outros
valores, exporte também `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`,
`KEYCLOAK_PUBLIC_URL` e `KEYCLOAK_ADMIN_USERNAME` conforme esse ambiente. O
script lê variáveis de ambiente, não o arquivo `deploy/.env` diretamente. A
senha em `SEED_USERS_PASSWORD` permite autenticar qualquer uma das duas contas
de demonstração no Keycloak.

O cliente já aceita `http://localhost:5173/*` como retorno de login e logout. Se
o volume `keycloak-data` já existia antes da mudança do realm, ajuste esses valores
no console, pois a importação preserva clientes existentes.

## Frontend e sessão

Para executar o frontend pelo Vite, crie `frontend/.env` a partir de
`frontend/.env.example`, caso ainda não exista, e use:

```dotenv
VITE_API_BASE_URL=/api
VITE_KEYCLOAK_URL=http://localhost:8081
VITE_KEYCLOAK_REALM=synapse
VITE_KEYCLOAK_CLIENT_ID=synapse-frontend
```

Em `frontend/`, execute `npm ci` e `npm run dev` e acesse
`http://localhost:5173`. O proxy do Vite encaminha `/api` para a API em
`http://localhost:8080`.

O login usa OIDC com PKCE. Os tokens ficam em memória; ao recarregar a página, o
frontend tenta recuperar a sessão por SSO silencioso. REST e SSE enviam Bearer e
aguardam a renovação do token antes de cada requisição ou abertura do stream.
Uma falha transitória de renovação permite nova tentativa sem descartar o
formulário; uma resposta 401 reinicia o login.

A API vincula o claim `sub` à conta em `usuarios.keycloak_sub`. Os papéis do realm
são `profissional-rh` e `auditor`; o papel inicial gravado na conta local é
`profissional_rh`. A aplicação uniforme das permissões e da posse dos jobs está
pendente na tarefa do middleware de autorização, conforme o
[ADR-006](../../docs/adrs/ADR-006.md).

Se executar a API fora do Compose, defina `KEYCLOAK_ENABLED=true` no ambiente da
API. O default de `application.yaml` é `false`; o Compose o habilita por padrão.
Nesse modo local, `KEYCLOAK_JWK_SET_URI` deve apontar para
`http://localhost:8081/realms/synapse/protocol/openid-connect/certs`, pois o nome
`keycloak` só é resolvido dentro da rede Docker.

## Preparação para staging

A promoção manual para staging exige configurar o ambiente público. O realm
versionado aceita apenas a origem `http://localhost:5173`; mudar as variáveis do
frontend não altera os retornos permitidos no Keycloak.

- Configure uma URL pública acessível pelo navegador para o Keycloak. O Caddyfile
  versionado ainda não publica uma rota para esse serviço.
- Use essa URL em `KEYCLOAK_PUBLIC_URL` e `VITE_KEYCLOAK_URL`; configure
  `KEYCLOAK_ISSUER_URI` como a mesma URL seguida de `/realms/synapse`.
- Mantenha `KEYCLOAK_JWK_SET_URI` acessível à API pela rede Docker.
- Ajuste `Valid Redirect URIs`, `Valid Post Logout Redirect URIs` e `Web Origins`
  do cliente para a origem pública do frontend, além de `CORS_ALLOWED_ORIGINS`
  da API.
- Reconstrua o frontend após alterar `VITE_*`, pois esses valores são incorporados
  ao bundle durante o build.

Em realms já existentes, aplique os ajustes pelo console: a importação de
inicialização não substitui o realm persistido. O serviço versionado usa
`start-dev`; a configuração do ambiente de staging precisa considerar esse modo
de execução antes da promoção.

A validação pelo navegador deve cobrir login, recuperação da sessão após recarga,
renovação após a expiração do access token, recebimento de progresso por SSE e
logout. Os testes automatizados não substituem essa validação no endereço público.

## Tema de login

O tema visual `synapse` é montado no container pelo Compose. Após alterar arquivos
em `deploy/keycloak/themes/`, recrie somente o Keycloak:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --force-recreate keycloak
```

O símbolo exibido pelo tema está em
`deploy/keycloak/themes/synapse/login/resources/img/synapse-simbolo.png`. Ele foi
copiado a partir de `frontend/src/assets/imagens/synapse-simbolo.png` para que o
container possa montar o diretório inteiro do tema em modo somente leitura.

Em um realm criado anteriormente, selecione uma vez o tema no console:
**synapse → Realm settings → Themes → Login theme → synapse → Save**. Realms novos
recebem essa configuração pelo arquivo de importação.

`KEYCLOAK_PUBLIC_URL` deve ser a mesma URL pública configurada em
`VITE_KEYCLOAK_URL`. A API busca as chaves pela rede Docker, mas valida o emissor
presente no token com essa URL pública.
