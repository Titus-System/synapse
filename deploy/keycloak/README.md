# Keycloak local

Suba a identidade local junto dos serviços necessários:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build keycloak postgres rabbitmq api
```

O console administrativo fica em `http://localhost:8081/admin/`. As credenciais do
administrador vêm de `KEYCLOAK_ADMIN_USERNAME` e `KEYCLOAK_ADMIN_PASSWORD` em
`deploy/.env`.

O import cria o realm `synapse` e o cliente público `synapse-frontend`. Crie os
usuários em **synapse → Users**; não crie contas de uso da aplicação no realm
`master`. O usuário autenticado recebe uma conta local na primeira chamada à API.

O cliente já aceita `http://localhost:5173/*` como retorno de login e logout. Se
o volume `keycloak-data` já existia antes da mudança do realm, ajuste esses valores
no console, pois a importação preserva clientes existentes.

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
