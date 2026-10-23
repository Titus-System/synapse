# Keycloak e acesso ao Synapse (E11)

## Testar no Windows 11 começando pelo frontend

Com Docker Desktop (containers Linux) aberto, execute na raiz:

```bash
python deploy/keycloak/local/iniciar.py
```

O inicializador cria seu próprio `.env` e sobe frontend, API, banco, RabbitMQ,
Keycloak e caixa de e-mails local. Não exige `deploy/.env`, `python3`, Java ou
Node instalados no host. Acesse `http://localhost:5173/nova-regra` e leia os
e-mails em `http://localhost:8025`.

Siga o [roteiro completo no Windows](local/README.md) para cadastrar, verificar,
recuperar a senha, voltar ao login e conferir o mesmo vínculo na API/banco.
Esse ambiente é separado da instalação compartilhada descrita a seguir.

## Instalação compartilhada e ambiente publicado

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
retornado pelo Keycloak e `senha_hash` nulo. São sete jobs de demonstração:
quatro vinculados a `develop@synapse.pro` e três vinculados a `staging@synapse.pro`
no status `aguardando_decisao_usuario`. Em uma nova execução, o script reutiliza as contas,
redefine a senha de ambas e corrige a posse dos jobs criados por versões antigas
do seed.

Com o Keycloak e o banco já iniciados e as migrations da API aplicadas, instale
a dependência do script e execute-o a partir da raiz:

```bash
python -m pip install -r deploy/scripts/requirements.txt
python deploy/scripts/seed.py
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

O arquivo de importação inclui as origens conhecidas do projeto. Aplique o
procedimento E11 abaixo para restringir o cliente à origem do ambiente, também
quando o volume `keycloak-data` já existir.

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

A API vincula o claim `sub` à conta em `usuarios.keycloak_sub`. O token deve conter
exatamente um papel de negócio: `profissional-rh` → `profissional_rh` ou
`auditor` → `auditor`. A API rejeita ambos ou nenhum antes de escrever no banco.
Os papéis técnicos do Keycloak são ignorados. As permissões e a posse dos jobs
seguem o [ADR-006](../../docs/adrs/ADR-006.md).

Se executar a API fora do Compose, defina `KEYCLOAK_ENABLED=true` no ambiente da
API. O default de `application.yaml` é `false`; o Compose o habilita por padrão.
Nesse modo local, `KEYCLOAK_JWK_SET_URI` deve apontar para
`http://localhost:8081/realms/synapse/protocol/openid-connect/certs`, pois o nome
`keycloak` só é resolvido dentro da rede Docker.

## Staging e CD

O Keycloak é publicado em `https://auth.synnapse.pro`. O Caddy termina TLS e
encaminha as requisições para `keycloak:8080`; o Keycloak interpreta os cabeçalhos
`X-Forwarded-*` enviados pelo proxy. A porta `8081` no host fica restrita a
`127.0.0.1`, para acesso local e por túnel SSH.

Antes da primeira implantação:

1. Aponte o DNS de `auth.synnapse.pro` para o droplet e libere `80`/`443`.
2. Configure `KEYCLOAK_ADMIN_PASSWORD` e os seguintes valores em `deploy/.env`
   **no droplet**:

   ```dotenv
   KEYCLOAK_ENABLED=true
   KEYCLOAK_PUBLIC_URL=https://auth.synnapse.pro
   KEYCLOAK_ISSUER_URI=https://auth.synnapse.pro/realms/synapse
   KEYCLOAK_JWK_SET_URI=http://keycloak:8080/realms/synapse/protocol/openid-connect/certs
   VITE_KEYCLOAK_URL=https://auth.synnapse.pro
   VITE_KEYCLOAK_REALM=synapse
   VITE_KEYCLOAK_CLIENT_ID=synapse-frontend
   CORS_ALLOWED_ORIGINS=https://app.synnapse.pro
   ```

3. Aplique o procedimento E11 abaixo com
   `SYNAPSE_FRONTEND_URL=https://app.synnapse.pro`. Ele configura retorno de
   login/logout, Web Origins e Base URL somente para a origem de staging,
   tanto em realms novos quanto existentes.
4. Implante o gateway e o Keycloak, recrie a API e reconstrua o frontend para
   aplicar as URLs. Os workflows correspondentes podem ser disparados manualmente
   em **Actions → Run workflow**, selecionando `staging`. Alterar o `.env` no
   servidor não dispara esses workflows.

O workflow `.github/workflows/cd-keycloak.yml` dispara em push para `staging`
quando houver mudanças em `deploy/keycloak/**`, `deploy/docker-compose.yml` ou
no próprio workflow. Também aceita disparo manual. Usa os mesmos secrets SSH e
a fila `cd-staging-deploy` dos outros componentes, obtém a imagem e recria apenas
o Keycloak, preservando o volume `keycloak-data`. O deploy aguarda o healthcheck
`/health/ready` e falha se o serviço não ficar pronto em 180 segundos.

A recriação aplica os arquivos do tema. A importação de inicialização cria realms
novos, mas não atualiza realms já persistidos: alterações no realm existente
devem ser aplicadas pelo procedimento E11 abaixo. O seed é executado manualmente e não participa
de nenhum fluxo de CI/CD.

O serviço usa `start-dev`, conforme o Compose compartilhado. A configuração
segue as orientações do Keycloak para
[proxy reverso](https://www.keycloak.org/server/reverseproxy) e
[healthcheck](https://www.keycloak.org/observability/health).

Após o deploy, confira o emissor em
`https://auth.synnapse.pro/realms/synapse/.well-known/openid-configuration` e valide
login, recarga da página, renovação de token, SSE e logout pelo frontend público.

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


## E11: o que é configurado

O cadastro e a recuperação usam os autenticadores nativos do **Keycloak 26.7.4**.
O frontend continua com Authorization Code + PKCE S256. Não há endpoints de
senha na API, nem alteração de migrations ou armazenamento de credenciais local.

| Recurso | Configuração |
| --- | --- |
| Cadastro | Nome completo, e-mail, senha e confirmação. O e-mail é o username das novas contas. |
| Perfil | Validação no servidor. Nome completo em `firstName`, e-mail obrigatório, atributos não gerenciados desabilitados. Sobrenome legado continua armazenado. |
| Papel inicial | Grupo padrão `/synapse-autocadastro`, contendo apenas `profissional-rh`. |
| Verificação | Obrigatória antes do acesso. Link de verificação válido por 30 minutos. |
| Recuperação | Resposta genérica para endereço existente, inexistente ou falha de envio. Link válido por 15 minutos. |
| Redefinição | Validação nativa, confirmação da senha e retorno obrigatório ao login. Tokens de ação não podem ser reutilizados. |
| Senha | Política inicial de pelo menos 12 caracteres, diferente do usuário/e-mail. Políticas preexistentes são preservadas. |
| URLs | Uma origem de frontend por ambiente, PKCE obrigatório, retorno de login/logout limitado a essa origem. |

Não acrescente `profissional-rh` ao composite `default-roles-synapse`: isso
poderia conceder esse papel também aos auditores que já possuem o composite.
Grupos padrão são atribuídos às contas novas, sem incluir automaticamente os
usuários existentes. Novos usuários criados pelo console ou pela Admin API
também recebem o grupo. Ao administrar uma conta especial, remova o grupo
antes de atribuir `auditor`; não conceda ambos os papéis. O formulário público
não expõe grupos nem papéis. O seed trata essa remoção somente no auditor que
ele acabou de criar e recusa conflitos nas contas já existentes. As contas de
demonstração são marcadas como verificadas, pois seus e-mails são fixtures.

Em 26.7.4, `verifyEmail=true` normalmente adia a definição da senha até depois
da verificação. O fluxo `synapse-registration` usa a opção nativa
`always_set_password_on_register_form=true` para manter senha e confirmação
no cadastro, como especificado no E11. A opção é depreciada pelo Keycloak:
revalide o fluxo antes de atualizar a imagem. Não substituímos a validação de
senha nem a verificação de e-mail por código próprio.

As telas de cadastro, recuperação, nova senha, verificação e confirmação são
herdadas dos templates nativos, com `template.ftl`, estilos e mensagens do
Synapse. `error.ftl` orienta a reiniciar pelo aplicativo para obter um novo link.
Essa herança mantém campos ocultos, ações e validações de perfil do provedor.

## Aplicação em realms novos e existentes

Execute em uma janela de manutenção e mantenha um backup do banco/volume do
Keycloak. O procedimento usa Admin API e não apaga usuários, senhas, sessões,
clientes, dados da aplicação ou o volume. **Não exclua o realm ou o volume para
aplicar o E11.** O import de inicialização só cria realms ausentes.
No primeiro provisionamento, conclua a configuração e valide o SMTP antes de
liberar a aplicação ao público.

1. Atualize o checkout e preencha `deploy/.env` a partir dos campos novos de
   `deploy/.env.example`. Defina `KEYCLOAK_ADMIN_PASSWORD`, SMTP e as duas URLs.
   O host SMTP precisa ser alcançável **pelo container do Keycloak**. `localhost`
   dentro do container não é o host nem o serviço de e-mail.
2. Recrie o Keycloak para carregar os templates e as opções de métricas:

   ```bash
   docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --force-recreate --wait keycloak
   ```

3. Com Python 3.10 ou superior no host, aplique a configuração. Não exige pip:

   ```bash
   python deploy/keycloak/configurar.py --env-file deploy/.env
   ```

4. No console, confirme **Realm settings → Email** e use **Test connection**
   com uma conta administrativa cujo e-mail esteja configurado. Esse teste
   envia um e-mail real. Depois execute os fluxos de validação abaixo.

Use o mesmo comando tanto no primeiro provisionamento quanto em atualizações.
O script copia os fluxos nativos somente quando os aliases Synapse não existem,
ajusta os autenticadores, aplica perfil, grupo, SMTP, URLs e eventos, e permite
reaplicação. Ele não modifica a identidade de nenhum usuário existente. Outros
atributos de perfil e de cliente são preservados. Os quatro campos nativos do
perfil seguem o contrato do E11. As origens antigas de desenvolvimento são
substituídas pela origem explícita do ambiente.

O script recusa fluxos de cadastro/recuperação com bindings personalizados e
permissões inesperadas nos grupos/papel padrão. Revise essas diferenças antes
de aplicá-lo em um realm diferente do estado versionado. Durante a aplicação,
cadastro e recuperação ficam desabilitados até a última etapa. Se houver uma
falha após essa etapa inicial, corrija a causa e execute novamente. O login de
usuários existentes permanece habilitado. Operações Admin API não formam uma
transação única; faça a aplicação com exclusividade administrativa.

Para suspender o autocadastro, desative **User registration** no realm. Não
remova o grupo nem suas associações: isso retiraria o acesso dos cadastrados.
Para reverter outras configurações, restaure os valores anteriores no console
ou o backup apropriado, sem recriar contas.

### SMTP e segredos

Configure `KEYCLOAK_SMTP_HOST`, `PORT`, `FROM`, `AUTH`, `USER`, `PASSWORD`,
`STARTTLS` e `SSL`. Use `587` + STARTTLS ou `465` + SSL conforme o provedor.
`FROM_DISPLAY_NAME` é `Synapse`; `REPLY_TO` é opcional. O remetente precisa estar
autorizado no provedor. O script rejeita STARTTLS e SSL simultâneos.

A senha pode vir de `KEYCLOAK_SMTP_PASSWORD_FILE`, arquivo secreto no host que
executa o script. Esse valor tem precedência sobre `KEYCLOAK_SMTP_PASSWORD`.
Proteja `deploy/.env`, o arquivo de senha e backups do Keycloak. A configuração
SMTP fica persistida no armazenamento do próprio Keycloak. Não versione nenhum
desses segredos nem exports completos que os contenham.

Variáveis exportadas prevalecem sobre `--env-file`. O arquivo aceita
`CHAVE=valor`, aspas externas e comentários em linhas próprias. Não executa
shell, não expande `$VAR` e não interpreta comentários ao final dos valores.
Não use `set -x`, dumps de configuração, logs HTTP de corpo ou logs DEBUG para
diagnosticar credenciais. O script não imprime payloads, senhas ou tokens.

`KEYCLOAK_SMTP_ALLOW_INSECURE=true` existe somente para o SMTP de teste local.
O script o rejeita se `KEYCLOAK_PUBLIC_URL` não for loopback. Em staging use TLS,
credenciais válidas e entrega real. O teste SMTP local não comprova SPF, DKIM,
DMARC, reputação ou entrega na caixa de entrada externa.

### URLs por ambiente

| Variável | Desenvolvimento | Staging |
| --- | --- | --- |
| `KEYCLOAK_PUBLIC_URL` | `http://localhost:8081` | `https://auth.synnapse.pro` |
| `KEYCLOAK_ADMIN_URL` | `http://localhost:8081` | URL HTTPS administrativa ou loopback de túnel SSH |
| `SYNAPSE_FRONTEND_URL` | `http://localhost:5173` | `https://app.synnapse.pro` |

As URLs são origens sem caminho ou curinga. `KEYCLOAK_PUBLIC_URL` deve coincidir
com `VITE_KEYCLOAK_URL`, com o emissor da API e com `KC_HOSTNAME`. O script usa
essa origem para links públicos do realm. Ele não reconstrói o frontend nem
altera o emissor configurado na API. A porta administrativa não precisa ser
exposta publicamente: execute no servidor ou use túnel SSH. O procedimento de
CD recria o Keycloak, mas não executa a atualização Admin API automaticamente.

Usuários antigos sem e-mail verificado precisarão confirmar o endereço no
próximo login. Isso não muda seu `sub`. Corrija antes endereços ausentes ou
obsoletos pelas rotinas administrativas do projeto; não marque contas reais
como verificadas em massa para contornar a confirmação.

## Testes automatizados

Configuração local, sem serviços externos:

```bash
python -m unittest discover -s deploy/keycloak/tests -p test_configuracao.py -v
```

Para instalar as dependências e rodar a integração em ambiente descartável,
use o mesmo comando em Git Bash e PowerShell:

```bash
python deploy/keycloak/local/iniciar.py testar
```

Ele usa Keycloak real e Mailpit dentro do Docker, evitando a conexão SMTP do
container para o Windows. O inicializador cria um venv, mostra progresso, limita
o tempo da suíte e encerra somente o projeto `synapse-e11-test`. Não usa nem
altera o realm `synapse` do ambiente manual. Consulte as portas e os resultados
esperados no [roteiro local](local/README.md#5-validar-erros-e-executar-a-suíte).

Para execução manual/CI, os comandos equivalentes são:

```bash
python -m pip install -r deploy/keycloak/tests/requirements.txt -r deploy/scripts/requirements.txt
docker compose -p synapse-e11-test -f deploy/keycloak/tests/compose.yml up -d --wait --wait-timeout 240
```

No Bash/Git Bash:

```bash
KEYCLOAK_E2E_URL=http://localhost:8180 KEYCLOAK_E2E_METRICS_URL=http://localhost:9000/metrics KEYCLOAK_E2E_MAILPIT_URL=http://localhost:8026 KEYCLOAK_E2E_SMTP_HOST=mailpit KEYCLOAK_ADMIN_USERNAME=admin KEYCLOAK_ADMIN_PASSWORD=e11-local-tests-only python -u -m unittest discover -s deploy/keycloak/tests -v -f
```

No PowerShell:

```powershell
$env:KEYCLOAK_E2E_URL="http://localhost:8180"
$env:KEYCLOAK_E2E_METRICS_URL="http://localhost:9000/metrics"
$env:KEYCLOAK_E2E_MAILPIT_URL="http://localhost:8026"
$env:KEYCLOAK_E2E_SMTP_HOST="mailpit"
$env:KEYCLOAK_ADMIN_USERNAME="admin"
$env:KEYCLOAK_ADMIN_PASSWORD="e11-local-tests-only"
python -u -m unittest discover -s deploy/keycloak/tests -v -f
```

Depois, encerre somente o projeto de teste:

```bash
docker compose -p synapse-e11-test -f deploy/keycloak/tests/compose.yml down -v
```

A suíte cria e remove realms exclusivos `e11-test-<uuid>` e não utiliza o realm
`synapse`. O SMTP fica na rede Docker; a caixa de testes pode ser consultada em
`http://localhost:8026` enquanto os containers estiverem ativos.
Para Keycloak executado diretamente no host, omita `KEYCLOAK_E2E_MAILPIT_URL` e
use `KEYCLOAK_E2E_SMTP_HOST=127.0.0.1`: somente nesse modo a suíte abre um SMTP
`aiosmtpd` temporário na porta `1025` do host. Sem
`KEYCLOAK_E2E_URL`, os testes de integração são explicitamente ignorados, não
contabilizados como validação dos fluxos.

A validação visual opcional usa Playwright e um Chromium local. Instale
`playwright`, execute `python -m playwright install chromium` e defina
`SYNAPSE_TEST_CHROMIUM` com o caminho do executável. O teste valida cadastro e
recuperação em desktop/mobile, ausência de overflow horizontal, alternância
de visibilidade da senha e erros JavaScript. Capturas só são gravadas se
`KEYCLOAK_SCREENSHOT_DIR` estiver definido.

A workflow `verificar-keycloak.yml` executa os testes de configuração e os fluxos
nativos com SMTP capturado no Mailpit em PRs que alterem esses arquivos. O teste visual é
opcional e não roda nessa workflow.

Para regressão do provisionamento/posse na API, execute também o gate existente
com Java 21, Maven e Docker/Testcontainers disponíveis:

```bash
cd api
./verify.sh
```

## Validação no ambiente com e-mail real

A entrega do código não encerra o aceite de staging. Registre o resultado de:

1. Cadastro de conta nova, nome/e-mail inválidos, senha curta ou divergente e
   tentativa duplicada. Nenhum formulário deve aceitar seleção de papel.
2. Mensagem real de verificação recebida. Antes de verificar, o acesso não pode
   terminar em token válido do frontend. Depois, confira `email_verified=true`
   e somente `profissional-rh` entre os papéis de negócio.
3. Primeira chamada autenticada a `/jobs`: uma linha local criada/resolvida.
   Repetir o acesso não pode criar outra linha. Não grave os tokens de teste.
4. Conta existente com regra/campanha: registre internamente `usuarios.id`,
   `usuarios.keycloak_sub` e os IDs dos jobs acessíveis, sem expor dados pessoais.
   Recupere a senha e confirme os mesmos IDs, quantidade de usuários e posse.
5. Recuperação para endereço existente e inexistente: mesma mensagem pública.
   Confira remetente, URL HTTPS e domínio correto no e-mail recebido.
6. Senhas divergentes na redefinição, link expirado, adulterado e reutilizado.
   Todos devem impedir a mudança e permitir iniciar nova tentativa.
7. Nova senha aceita, antiga rejeitada em janela anônima. Recuperação retorna ao
   login. Verifique também logout e novo login, recarga e renovação da sessão.
8. Auditor anterior preservado, sem receber `profissional-rh`, e acesso operacional
   negado conforme a matriz de autorização já existente.

O Keycloak mantém o identificador do usuário ao redefinir uma credencial. A API
resolve esse identificador por `usuarios.keycloak_sub`, reaproveita `usuarios.id`
e não altera `jobs.usuario_id`. Os testes de identidade no Keycloak e os testes
de provisionamento da API são evidências complementares; confirme a cadeia
completa em staging antes de marcar a definição de concluído do épico.

## Observabilidade e diagnóstico

Eventos de cadastro, verificação, recuperação, login e logout são armazenados
no Keycloak por sete dias. Consulte **Realm settings → Events** e filtre sucesso
e erro. Detalhes de eventos administrativos ficam desabilitados para não salvar
payloads de configuração. E-mails/IDs presentes nos eventos do provedor exigem
acesso administrativo restrito. Não envie conteúdo de mensagens ou tokens aos
logs do Synapse.

O Compose habilita as métricas nativas de eventos, expostas na interface interna
`9000/metrics`, sem publicar essa porta no Compose da aplicação. O contador
`keycloak_user_events_total` distingue evento, resultado/erro e realm. Não
adicionamos métricas com usuário, token ou URL. Esses contadores medem eventos,
não usuários únicos; reiniciam com a instância. A suíte consulta o endpoint após
exercitar falha de login e envio de recuperação. A coleta pelo Alloy/Grafana
não faz parte desta alteração e precisa ser configurada/validada separadamente.

Se o e-mail não chegar, confira eventos de envio, disponibilidade SMTP, TLS,
remetente autorizado e spam. A mensagem pública de recuperação permanece
genérica inclusive quando o envio falha. Não use essa mensagem como confirmação
de que o servidor SMTP aceitou o e-mail. Links apontando ao host errado indicam
divergência entre hostname, URL pública do realm e proxy.

Referências oficiais: [administração](https://www.keycloak.org/docs/26.7.0/server_admin/index.html),
[temas](https://www.keycloak.org/docs/latest/server_development/#_themes),
[métricas de eventos](https://www.keycloak.org/observability/event-metrics).


Os resultados e limites da validação desta entrega estão em
[VALIDACAO-E11.md](VALIDACAO-E11.md).
