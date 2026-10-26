# E11 no Windows 11: do frontend à nova senha

Este ambiente sobe o frontend real, API, PostgreSQL 18, RabbitMQ, Keycloak e
Mailpit. O Mailpit recebe os e-mails localmente: você abre as mensagens pelo
navegador, sem conta SMTP, Gmail ou configuração de produção.

O projeto Docker se chama `synapse-e11-local`, com volumes próprios. Ele não
utiliza `deploy/.env` nem `frontend/.env`. As senhas são geradas na primeira
execução em `deploy/keycloak/local/.env`, ignorado pelo Git. Preserve esse
arquivo nas próximas execuções: as senhas correspondem aos volumes persistidos.

## 1. Preparar e iniciar

Pré-requisitos: Docker Desktop iniciado com **containers Linux**, Python 3.10+
disponível como `python`, e acesso à internet para baixar imagens/dependências.
Python 3.13 é compatível com o inicializador. Java, Node, Maven e PostgreSQL não
precisam estar instalados no Windows: os builds e serviços ficam no Docker.

Extraia os arquivos recebidos **na raiz do projeto**, substituindo os existentes.
Abra Git Bash ou PowerShell nessa raiz e execute, um comando por vez:

```bash
python --version
docker version
docker compose version
python deploy/keycloak/local/iniciar.py
```

Os comandos são iguais nos dois terminais. No Windows, use `python`, que já
funcionou nos testes anteriores; o alias `python3` da Microsoft Store não é
necessário. Se a instalação só disponibilizar `py`, use
`py -3 deploy/keycloak/local/iniciar.py`.

O comando compila API/frontend, inicia os serviços, aplica as migrations e
configura cadastro, e-mail, recuperação e URLs do realm. O primeiro build pode
levar vários minutos; acompanhe a saída de Maven/npm/Docker. Só abra o fluxo
quando aparecer **Ambiente pronto**.

| Serviço | Endereço |
| --- | --- |
| Synapse | http://localhost:5173/nova-regra |
| Caixa de e-mails de teste | http://localhost:8025 |
| Console do Keycloak | http://localhost:8081/admin/ |
| Saúde da API | http://localhost:8080/actuator/health |

Use exatamente `localhost` nos links, sem trocar por `127.0.0.1`: emissor OIDC,
cookies e retornos foram configurados para essa origem. No console do Keycloak,
o usuário é `admin` e a senha é o valor de `E11_ADMIN_PASSWORD` no `.env` local.
Você não precisa acessar esse console para cadastrar ou recuperar a senha.

As portas **5173, 8080, 8081 e 8025** precisam estar livres. Se já houver Vite,
API ou Keycloak antigos usando essas portas, pare esses processos/containers
pelo terminal correspondente ou Docker Desktop antes de iniciar este ambiente.
Não exclua seus volumes. O inicializador não para outros projetos Docker.

## 2. Cadastrar pelo frontend e verificar o e-mail

1. Abra uma janela anônima e acesse o Synapse pelo endereço acima. O frontend
   encaminhará ao login com o tema Synapse.
2. Clique em **Criar conta**. Informe nome completo, `pessoa@example.test`, uma
   senha com pelo menos 12 caracteres e a confirmação. Escolha uma senha
   exclusiva para este teste e não use credenciais reais.
3. Envie o formulário. O Keycloak deve pedir a verificação do e-mail.
4. Na **mesma janela anônima**, abra uma segunda aba em
   `http://localhost:8025`. Abra a mensagem destinada a `pessoa@example.test` e
   clique no link de verificação. Se o navegador abrir uma nova aba, mantenha-a
   nessa mesma janela para preservar a sessão.
5. Conclua a confirmação e retorne ao Synapse. Se o login for solicitado,
   informe o e-mail e a senha recém-criados.
6. Abra **Salvas** na navegação. Uma lista vazia é esperada para conta
   nova. Nas ferramentas do navegador (F12 → Network/Rede), filtre por `jobs`:
   o GET para `/api/jobs` deve responder **200**. Não copie o cabeçalho
   `Authorization` nem o conteúdo dos tokens.

Ver o formulário do Synapse confirma o retorno do login; o GET 200 confirma
também o acesso à API e o provisionamento da conta local.

## 3. Recuperar a senha começando pelo frontend

1. No Synapse, clique no ícone do perfil no canto superior direito e em
   **Sair da conta**. Se o Keycloak pedir confirmação, confirme a saída nessa
   tela. Você deve voltar ao login.
2. Clique no link de recuperação de senha e informe `pessoa@example.test`.
3. A tela deve apresentar uma resposta genérica, sem confirmar a existência da
   conta. Abra o Mailpit e selecione a **nova mensagem de recuperação**, não a
   mensagem anterior de verificação.
4. Abra o link e defina uma nova senha, diferente da anterior, com confirmação
   igual e pelo menos 12 caracteres. Conclua e use o retorno ao login.
5. Tente entrar com a **senha antiga**: deve ser rejeitada. Entre com a **nova**:
   o Synapse deve abrir e `/api/jobs` deve continuar respondendo 200.
6. Saia da conta, feche todas as janelas anônimas e abra outra. Tente reutilizar
   o link de recuperação: ele não pode permitir outra redefinição e deve
   orientar uma nova solicitação pelo login do aplicativo.

Essa é a recuperação por esquecimento do E11. Não foi acrescentada uma tela de
troca de senha dentro do perfil de um usuário já autenticado.

## 4. Conferir que o vínculo local foi preservado

Execute o comando abaixo **antes e depois** da recuperação. Ele só consulta os
identificadores locais, papel e vínculos de jobs; não exibe senha ou token:

```bash
docker compose -p synapse-e11-local --env-file deploy/keycloak/local/.env -f deploy/keycloak/local/compose.yml exec -T postgres psql -U postgres -d synapse_db -c "SELECT u.id, u.keycloak_sub, u.papel, u.senha_hash IS NULL AS sem_senha_local, count(j.id) AS jobs FROM usuarios u LEFT JOIN jobs j ON j.usuario_id = u.id GROUP BY u.id ORDER BY u.id;"
```

Após o primeiro acesso, a conta deve ter `keycloak_sub` preenchido,
`papel = profissional_rh` e `sem_senha_local = t`. Após redefinir e entrar de
novo, o `id`, o `keycloak_sub` e a quantidade de contas devem permanecer iguais.
Se a conta já tinha jobs neste ambiente, a quantidade e os vínculos devem ser
preservados. No ambiente novo a quantidade de jobs será zero; esse resultado
não comprova preservação de dados preexistentes.

Para consultar também os identificadores dos dados associados:

```bash
docker compose -p synapse-e11-local --env-file deploy/keycloak/local/.env -f deploy/keycloak/local/compose.yml exec -T postgres psql -U postgres -d synapse_db -c "SELECT id, usuario_id, status FROM jobs ORDER BY id;"
```

Os serviços de geração por IA e simulação não são iniciados aqui. O processo
completo coberto por este ambiente é **cadastro/recuperação → login → frontend
→ API → conta local**. Para produzir novas simulações, use o ambiente completo
do projeto, com seus provedores e datasets, conforme o manual de instalação.

## 5. Validar erros e executar a suíte

Pelo navegador, confira também: nome/e-mail inválidos, senha curta,
confirmação divergente, cadastro duplicado e recuperação para
`inexistente@example.test`. A resposta de recuperação deve ser a mesma da
conta existente e não deve chegar mensagem para o endereço inexistente.
Para conferir expiração manual, solicite um link e aguarde mais de 15 minutos,
sem usá-lo. Ele deve exigir uma nova solicitação. Não altere o relógio do PC.

Para os casos automatizados, na raiz:

```bash
python deploy/keycloak/local/iniciar.py testar
```

Esse comando cria `deploy/keycloak/local/.venv`, instala as dependências,
sobe **outro** Keycloak em 8180 e outro Mailpit em 8026, executa os testes e
encerra somente `synapse-e11-test`. Também usa a porta 9000 para métricas.
Não é preciso ativar o venv, exportar variáveis ou iniciar SMTP no Windows.
O ambiente manual em 5173 continua aberto.

São **24 testes descobertos**: 15 de configuração/inicializador e 9 de fluxos.
O teste visual opcional é ignorado nesse comando (23 passam, 1 skip quando
tudo estiver correto). A suíte HTTP verifica PKCE, e-mail, papéis, erros,
senha antiga, identidade, expiração, reutilização, logout e métricas; não dirige
o frontend nem comprova persistência no PostgreSQL. Os passos 2–4 fazem essa
validação conjunta. A execução local de referência dos 20 testes anteriores,
incluindo o visual, levou 82 segundos; o tempo do seu PC pode variar.

Cada caso agora mostra a etapa atual e uma mensagem de espera a cada 10 segundos.
As requisições têm timeout e o inicializador limita a execução da suíte a
10 minutos após subir os serviços. O texto de um teste terminado em `...`
sozinho não prova travamento: antes, o unittest não mostrava o progresso interno.

Se quiser apenas testar configuração, sem Docker e sem instalar dependências:

```bash
python -m unittest discover -s deploy/keycloak/tests -p test_configuracao.py -v
python -m unittest discover -s deploy/keycloak/tests -p test_local.py -v
```

## 6. Parar, reiniciar e diagnosticar

```bash
python deploy/keycloak/local/iniciar.py status
python deploy/keycloak/local/iniciar.py logs
python deploy/keycloak/local/iniciar.py parar
```

`parar` preserva volumes e contas. Para iniciar novamente, repita o comando
sem argumento. As mensagens do Mailpit são temporárias e podem sumir quando
o container for recriado. Não apague o `.env` local com volumes existentes.

| Sintoma | Verificação |
| --- | --- |
| `couldn't find env file: deploy/.env` | É um comando do ambiente compartilhado. Neste roteiro use `local/iniciar.py`; ele cria o próprio `.env`. |
| `Python não foi encontrado` ao usar `python3` | Use `python`, como nos comandos acima, ou o launcher `py -3`. |
| `WinError 10049` / espera no envio SMTP | Use a ação `testar`, que configura Mailpit dentro do Docker; não use as antigas variáveis com `host.docker.internal`. |
| Porta já ocupada | Confira os containers no Docker Desktop e os processos locais. Pare somente o que estiver usando uma das portas listadas. |
| Container `unhealthy` | Execute `logs`. Para detalhes do banco/broker, use o comando abaixo. |
| Tela do Synapse abre, mas `/api/jobs` falha | Confira API saudável, `KEYCLOAK_ENABLED=true` no Compose local e a configuração aplicada ao realm; repita o inicializador após corrigir a causa. |
| Nenhum e-mail no Mailpit | Confirme Keycloak/Mailpit saudáveis. Recuperação de endereço inexistente não envia mensagem. A mensagem genérica não comprova entrega. |

```bash
docker compose -p synapse-e11-local --env-file deploy/keycloak/local/.env -f deploy/keycloak/local/compose.yml logs --tail 80 postgres rabbitmq
```

Se a inicialização falhar, corrija a causa informada e repita o comando; ele
reutiliza os volumes. Compartilhe somente a etapa e o erro, sem `.env`, senhas,
tokens, cabeçalhos Authorization ou URLs completas dos e-mails.

## Produção e limites da validação

**Não é necessário mudar o `.env` de produção para este teste local.** Para
habilitar E11 no ambiente publicado, é necessário configurar SMTP real,
remetente autorizado e URLs públicas e aplicar `configurar.py` no realm já
existente, seguindo [o procedimento de implantação](../README.md).

O Mailpit captura SMTP real dentro do ambiente, mas não entrega em caixas de
entrada externas. Os resultados efetivamente executados e os limites desta
entrega estão em [VALIDACAO-E11.md](../VALIDACAO-E11.md), inclusive a ausência
de Windows/Docker no ambiente onde o pacote foi preparado.
