# T-220 — revisão final das etapas 1 e 2

Data: 14/10/2026. Branch: `feature/t-220-motor-reextracao`.
Base: `27b64f75d71063a2eb89235bd119432ad020d56d`, develop remoto conhecido e
ancestral comum da branch. A branch develop local está atrasada em `9260389`;
o diff usa a base efetiva da tarefa para não incluir alterações de outras tarefas.

## Resultado da integração

As duas etapas estão integradas e passaram nas verificações locais disponíveis.
`reextrair_regra` recebe RepresentacaoRegra, parâmetros atuais, conflitos, texto
da correção e competências publicadas; chama o modelo sem ferramentas, desserializa
JSON com Decimal e rejeição de duplicatas e invoca `aplicar_operacoes_correcao`.
Retorna regra validada, parâmetros completos, diagnósticos e dados da chamada para
futura auditoria. Nenhum defeito funcional do motor exigiu reimplementação.

A interface, exceções e limites estão em `codegen/docs/correcao.md`. A integração
operacional com grafo/banco/RabbitMQ permanece fora desta tarefa.

## Problemas encontrados e correções

- Ruff apontou SIM105 no tratamento da exceção do provedor. Substituído por
  `suppress(Exception)`, mantendo o lançamento sanitizado fora do contexto original.
- O prompt citava `orçamento` onde nomeava campos do schema; corrigido para o nome
  canônico `orcamento`. A documentação do prompt esclarece que textos do contexto
  também são dados, não instruções.
- O teste de chamada dizia verificar schema, mas não inspecionava os kwargs.
  Agora compara schema e MIME exatos, além da mensagem efetivamente enviada.
- Os casos de bloqueio/truncamento usavam `{}`, já inválido independentemente do
  motivo. Agora usam um envelope válido e verificam a mensagem de falha específica.
- A asserção de rebaixamentos aceitava lista vazia por `all([])`. Agora exige os
  dois diagnósticos completos, com refs, motivos e construtos corretos.
- Acrescentados testes de precisão monetária fracionária, cópia dos metadados e
  preservação das entradas, consumo de tokens, texto vazio, cancelamento e falha
  sanitizada quando parâmetros não podem formar um resultado contratualmente válido.
- Documentação da etapa 1 atualizada para incluir a chamada assíncrona existente.
- Ambiente virtual incompleto regularizado com `poetry install --no-root
  --no-interaction`, usando o lock existente. Nenhum manifesto ou dependência
  declarada foi alterado. Log: `ambiente-install.txt`.

## Arquivos da T-220

Alterados em relação à base: `codegen/.gitignore`, `codegen/app/extracao/motor.py`.
Criados: `codegen/app/extracao/{correcao,montagem,schema_correcao,reextracao}.py`,
`codegen/app/graph/prompts/reextraction.py`, `codegen/docs/correcao.md` e
`codegen/tests/app/extracao/{test_correcao,test_reextracao,test_reextracao_llm}.py`.

Nesta revisão, somente reextracao.py, reextraction.py, test_reextracao.py e a
documentação foram ajustados. Nenhum teste anterior da extração inicial foi alterado.
`t220-etapa2.zip` e `t220-etapa2/` são materiais de distribuição já presentes na raiz;
foram preservados e constam do status, mas não integram o diff de código da entrega.

## Verificações e resultados

Windows sem make: executados os equivalentes do Makefile via Poetry com o ambiente
existente explicitado, sem instalar hooks ou fazer staging:

```powershell
$env:VIRTUAL_ENV = 'C:\Users\eduar\AppData\Local\pypoetry\Cache\virtualenvs\codegen-5f5nqeI2-py3.13'
poetry run python scripts/preparar_contratos.py
poetry run ruff check app/ tests/
poetry run ruff format --check app/ tests/
poetry run mypy app/
poetry run pytest -p no:cacheprovider -q --tb=short -ra
```

Ruff e formatação foram aplicados somente aos arquivos tocados antes do gate;
as verificações integrais usaram modo somente leitura para preservar arquivos
fora do escopo. `-p no:cacheprovider` evita o problema local de permissão no cache.

| Verificação | Resultado | Evidência |
| --- | --- | --- |
| Inspeção inicial branch/status/diff | branch correta, diff sem erros | status final e histórico da sessão |
| Correção + reextração antes dos ajustes | 59 passaram | focados-inicial.txt |
| Focados finais + regressão inicial | 126 passaram em 2,64 s | focados-final.txt |
| Ruff integral | passou | gate-ruff.txt |
| Formatação integral | 161 arquivos conformes | gate-format.txt |
| mypy integral | 79 módulos sem erros | gate-mypy.txt |
| pytest integral no sandbox | 832 passaram, 65 skips, 22 erros de preparação por permissão | gate-pytest.txt |
| Somente os 22 impedidos, fora do sandbox | 22 passaram em 15,57 s | gate-pytest-retry.txt |

Resultado consolidado do pytest: **854 aprovados e 65 skips condicionais**, sem
falhas remanescentes. Não foi repetido o gate inteiro: apenas os 22 testes cujo
`tmp_path` não pôde acessar a pasta temporária foram repetidos com autorização.
Não houve mudanças de código entre essas duas execuções.

Comando dos focados finais: `poetry run pytest -p no:cacheprovider
tests/app/extracao/test_correcao.py tests/app/extracao/test_reextracao.py
tests/app/extracao/test_motor.py tests/app/extracao/test_registro.py
tests/app/extracao/test_falhas.py tests/app/extracao/test_parametros.py
tests/app/extracao/test_chamada.py -q --tb=short`.

Os skips são condições já previstas: ausência de credencial do modelo (26 casos)
e infraestrutura/flags de integração com API/Postgres/RabbitMQ (39 casos). Não
foram adicionados skip/xfail para ocultar defeitos nem alteradas asserções para
aceitar comportamento incorreto. Contratos foram preparados pelo script de build;
fontes compartilhadas não foram modificadas.

## Evidências RED da etapa 2

Mutação controlada da função pública para devolver dados sem chamar/processar o
modelo: **19 testes falharam**, por resultados/diagnósticos ausentes, chamada não
efetuada ou exceções esperadas não lançadas. Evidência:
`red-etapa2-orquestracao.txt`.

Mutação independente removendo o texto da correção do compartimento não confiável:
o teste do prompt falhou na comparação do texto. Evidência:
`red-etapa2-prompt.txt`. Os arquivos foram restaurados byte a byte em `finally`
e a restauração conferida antes da validação final. Assim, os **20 casos unitários
da etapa 2** foram observados falhando. O RED dos 43 casos da etapa 1 não foi repetido.
O teste opcional real não foi exercitado nem demonstrado RED sem credencial.

## Compatibilidade, segurança e critérios atendidos

- T-203: a montagem compartilhada mantém construtos habilitados, lastro existente
  e fallback genérico; regressão da extração inicial passou.
- T-277/T-278: parâmetros permanecem separados, completos e validados; remoção é
  ausência, não null; valores incoerentes e períodos fora das publicadas não são
  corrigidos automaticamente. As três dependências constam da base já confirmada.
- Schema fechado das seis operações, validação global separada da recuperação por
  operação, preservação dos campos não mencionados e refs sequenciais ao final.
- Desserialização com Decimal e rejeição de chaves duplicadas em qualquer nível.
- Nenhum bind de ferramentas, avaliação/importação de conteúdo da IA ou execução
  dinâmica. Instruções fixas, contexto e correção separados no prompt.
- Falhas permanentes herdam FalhaDoJobError e usam `extracao_parametros`; erros do
  provedor permanecem não permanentes e sanitizados. Cancelamento é propagado.
- Resultado e chamada não expõem conteúdo no repr. Não há logs de conteúdo nos
  módulos revisados; erro público não encadeia causa/contexto privado do provedor.
- Imutabilidade e precisão monetária verificadas através da chamada pública.

## Diagnósticos, teste real e pendências

`DiagnosticoOperacao` continua interno e é preservado em ResultadoReextracao junto
dos Rebaixamento válidos. Nenhuma serialização tenta gravar essa união no schema
fechado de rebaixamentos. Nenhum motivo incorreto foi fabricado. A decisão de
persistência permanece documentada e exige autorização de contrato; não bloqueia
a execução em memória da T-220, mas precisa ser resolvida antes de persistir na T-221.

Teste real: **não executado**, pois `get_settings().GOOGLE_API_KEY` não está
configurada no ambiente efetivo dos testes. Verificada somente a presença booleana,
sem expor credenciais. O SDK já está instalado; não se atribui esse limite à falta
de dependência. Compatibilidade efetiva com a API do provedor ainda não comprovada.

O motor encapsula erros de chamada sem preservar o código HTTP original. Logo, o
helper de retry 503 usado no teste opcional não identifica o erro após sanitização;
em indisponibilidade, o teste falha de forma sanitizada, sem falso sucesso ou skip.
O retry configurado no cliente do provedor continua independente desse helper.

Não adicionados nó, banco, broker, publicação, histórico T-224, E2 ou runtime novo.
Não instrumentados logs/métricas do fluxo nesta revisão; exportação e coleta não
verificadas. A integração ainda ausente deve implementar e validar observabilidade
antes de ativar o fluxo na aplicação. Não se afirma que painéis recebem esses dados.

Antes do PR: revisar o diff, decidir se haverá validação real com credencial e
registrar os limites de integração acima. A revisão humana e a CI continuam sendo
o portão final. Não há falha local remanescente na seleção executável desta tarefa.
Nenhum staging, commit, push, merge ou rebase foi realizado.

Artefatos: `t220-final.diff` contém os 11 arquivos de código/documentação da tarefa,
incluindo os 9 não rastreados; `t220-final-status.txt` registra todo o estado da árvore.
O diff foi validado com `git apply --check --reverse` e `git diff --check`.
