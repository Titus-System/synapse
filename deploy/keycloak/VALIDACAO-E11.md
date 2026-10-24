# Evidências de validação — E11

Validação sobre o projeto enviado em `develop`, com Keycloak **26.7.4** e Java 21.
O escopo da entrega é configuração/tema de identidade, procedimento de aplicação,
seed de demonstração e testes. Não houve alteração no código de produção da API
ou do frontend, nem migrations, endpoints de senha ou novos providers Java.

## Resultado da revisão para Windows

| Verificação | Resultado |
| --- | --- |
| Configuração Python e isolamento do inicializador | 15 testes aprovados |
| Keycloak 26.7.4 + Mailpit 1.27.4 + navegador | 9 testes aprovados |
| API: `UsuarioAtualTests` | 15 testes aprovados |
| API: `AutorizacaoJobsTests` | 152 testes aprovados |
| API: `AutorizacaoJobsPersistenciaTests` | 11 testes ignorados por ausência de Docker |
| Compilação/empacotamento da API com Java 21 | Aprovados |
| Frontend: `npm run build` (TypeScript + Vite) | Aprovado |
| Navegador iniciando pelo frontend real: cadastro e recuperação | Aprovado até o retorno autenticado; API/banco não disponíveis nessa execução |
| Compose local e de testes: `config --quiet` | Aprovados com Compose 5.6.1 |
| Ruff, compilação Python e `git diff --check` | Aprovados |
| Inicializador sem Docker disponível | Saída com erro orientativo, sem traceback |

**191 testes aprovados, nenhuma falha na execução final e 11 testes de banco
não executados.** A execução conjunta de configuração + fluxos nativos passou
20 testes em 82,145 s. Os quatro testes novos do inicializador passaram em uma
execução separada. Não é uma medição de tempo do Windows do usuário.

## Comandos e ambiente

```bash
python -m unittest discover -s deploy/keycloak/tests -v -f
python -m unittest discover -s deploy/keycloak/tests -p test_local.py -v
ruff format --check deploy/keycloak/configurar.py deploy/keycloak/tests deploy/keycloak/local/iniciar.py
ruff check deploy/keycloak/configurar.py deploy/keycloak/tests deploy/keycloak/local/iniciar.py
python -m compileall -q deploy/keycloak/configurar.py deploy/keycloak/tests deploy/keycloak/local/iniciar.py deploy/scripts/seed.py
git diff --check
```

A integração rodou em Linux com as distribuições oficiais nativas do Keycloak
26.7.4 e Mailpit 1.27.4, e Chromium Headless 134 via Playwright. Foram definidos
`KEYCLOAK_E2E_URL`, `KEYCLOAK_E2E_METRICS_URL`, `KEYCLOAK_E2E_MAILPIT_URL`,
`KEYCLOAK_E2E_SMTP_HOST=127.0.0.1` e `SYNAPSE_TEST_CHROMIUM`. O SMTP nativo
usou loopback porque ambos os processos estavam no mesmo host. No Compose,
o destino SMTP é `mailpit`, acessível pela rede Docker.

Os fluxos fizeram requisições HTTP/OIDC reais, com PKCE S256 e links extraídos
das mensagens recebidas no Mailpit, sem mocks de cadastro ou redefinição. O
novo caminho de testes não abre servidor `aiosmtpd` no Windows. O README
contém a execução equivalente por Compose e o roteiro manual pelo frontend.

Na API, foram executados:

```bash
sh ./mvnw -DskipTests package
sh ./mvnw -Dtest=UsuarioAtualTests,AutorizacaoJobsTests,AutorizacaoJobsPersistenciaTests test
```

A execução local usou configurações externas de proxy/certificado para baixar
as dependências. O Mockito foi carregado por
`-DargLine=-javaagent:<caminho-do-mockito-core.jar>`, pois a anexação dinâmica de
agente à JVM não está disponível aqui. Nenhuma dessas adaptações alterou o
POM, Dockerfile ou testes da aplicação.

No frontend, `npm ci` e `npm run build` usaram Node 24, com URLs locais e
`VITE_API_BASE_URL=/api`. A compilação não comprova conectividade com a API.

Além dos testes contados acima, uma verificação com Chromium iniciou o frontend
compilado em `/nova-regra`, acessou Criar conta, preencheu o cadastro, consumiu
o link recebido no Mailpit e retornou ao Synapse autenticado. Em seguida,
encerrou a sessão pelo menu do perfil, confirmou o logout nativo, solicitou a
recuperação, definiu outra senha e voltou ao login. A senha antiga foi rejeitada
e a nova retornou ao frontend; o identificador no Keycloak permaneceu igual.
Não houve erro JavaScript não tratado nesse cenário.

Essa verificação usou Vite Preview para servir o frontend, Keycloak e Mailpit
nativos. A API/PostgreSQL não estavam ativos: as chamadas a `/api/jobs` falharam
por conexão indisponível e não foram substituídas por respostas simuladas. O
resultado comprova a integração frontend/Keycloak, não o provisionamento
persistente. A confirmação de logout observada está incluída no roteiro manual.

## Correções desta revisão

- Inicialização local pelo mesmo Python invocado pelo usuário, com geração e
  preservação de senhas em `.env` próprio, sem depender de `deploy/.env`.
- Serviços e volumes isolados em `synapse-e11-local`, com frontend servido em
  5173, API, PostgreSQL, RabbitMQ, Keycloak e caixa de mensagens Mailpit.
- SMTP de teste inteiramente na rede Docker, sem conexão ao host Windows.
- Dependências de teste instaladas em venv dedicado e procedimento igual em
  Git Bash e PowerShell.
- Progresso por etapa, heartbeat a cada 10 segundos e prazo máximo da suíte
  no inicializador, em vez de uma linha silenciosa indefinidamente.
- Conexões administrativas a loopback não usam o proxy do sistema; o teste
  exercita HTTP real com um proxy inválido configurado e exige acesso direto.
- Testes do inicializador confirmam preservação das senhas, recusa de `.env`
  incompleto e isolamento em relação a variáveis de outros projetos.

## Comportamentos exercitados

- Cadastro com nome completo, e-mail, senha e confirmação, seguido de mensagem
  de verificação, consumo do link e troca do authorization code por tokens.
- Token com e-mail verificado e somente `profissional-rh` entre os papéis de
  negócio, inclusive após envio malicioso de campos de papel no formulário.
- Nome ausente, e-mail inválido, senha curta e confirmação divergente, sem
  criação da conta. Cadastro duplicado sem duplicação de usuário no Keycloak.
- Mesma mensagem de recuperação para e-mail existente e inexistente.
- Confirmação divergente na redefinição, troca efetiva da senha, rejeição da senha
  anterior e manutenção do mesmo `sub` e dos mesmos papéis.
- Rejeição de link adulterado, expirado e reutilizado em outra sessão.
- Confirmação da alteração com retorno ao frontend e início de novo login,
  sem emissão automática de tokens pelo fluxo de recuperação.
- Atualização de realm com a estrutura anterior ao E11 e reaplicação, mantendo
  a conta e os papéis de um auditor preexistente.
- Seed executado e reaplicado com RH e auditor, sem dupla atribuição de papel.
- Renovação de token, logout OIDC e retorno à tela de login.
- Cadastro e recuperação em 1440 × 1000 e 390 × 844, sem overflow horizontal
  ou erros JavaScript, com controle funcional de visibilidade de senha.
- Eventos reais de erro de login e envio de recuperação e exposição do contador
  nativo no endpoint de métricas. Logs examinados sem as senhas de teste ou
  links contendo tokens de recuperação. Coleta pelo Grafana não foi testada.

## Limites e aceite pendente

Windows e Docker não estão disponíveis no ambiente de execução. Por isso, os
containers do novo ambiente local, a workflow do GitHub e os 11 testes de
persistência com PostgreSQL/Testcontainers não foram executados aqui. A validação
do Compose foi estrutural, não uma inicialização real dos containers. A distribuição nativa usada nos testes tem a mesma
versão de Keycloak fixada no Compose.

Não foram fornecidos ambiente de staging, conta de e-mail real ou credenciais
SMTP. A entrega externa de mensagens, TLS do provedor, DNS e retorno nos domínios
reais precisam ser validados pelo procedimento do README. O SMTP local valida
as mensagens e os links, mas não substitui essa homologação.

Os testes da API validam o provisionamento por `sub` e a autorização/posse com
os testes existentes. A manutenção dos registros e dos dados de uma conta real,
antes e depois da recuperação, ainda exige a validação conjunta com PostgreSQL
no ambiente. O E11 não deve ser marcado como totalmente homologado antes de
concluir essas verificações.
