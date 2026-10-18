# T-224 — implementação e relatório de verificação

## Alterações

- **Histórico (somente `SELECT`)**: `app/repositorio/rodadas_correcao.py` percorre `rodada_anterior_id` a partir da rodada associada à `submissao_correcao_id` corrente, filtrando **o mesmo `job_id` em cada nível**. Reúne conflitos e transcrições de até **cinco** rodadas anteriores, inclusive aquelas com reextração malsucedida, em ordem cronológica. Sem âncora, devolve histórico vazio.
- **Prompt e grafo**: o nó `reextract_rule` consulta esse histórico antes da reextração. O prompt contém os textos anteriores e os conflitos dentro de `dados_nao_confiaveis_da_correcao`, ao lado do texto corrente. Histórico é contexto; valores novos são conferidos exclusivamente contra a transcrição **corrente**. O mesmo prompt é usado na pesquisa de respostas já gravadas. Nenhum contrato de evento foi alterado.
- **Operações**: cada item do schema interno exige `trecho`, literal e não vazio. Ausência ou citação não contida no texto corrente produz `operacao_sem_trecho` e impede a mutação. A verificação determinística de campos do núcleo, elementos e parâmetros da simulação mantém os valores anteriores quando há `valor_sem_lastro`; elementos sem lastro verificável são preservados como `generico` com descrição segura, nunca com número inventado. Nenhuma verificação é delegada ao modelo.
- **Métricas**: `MOTIVOS_DE_REBAIXAMENTO` passou a conter os motivos usados pela reextração, incluindo `operacao_sem_trecho` e `valor_sem_lastro`; nome, estrutura e labels do contador original mantidos. Logs operacionais continuam sem histórico ou transcrição.
- **Testes**: falsos do repositório e grafo, verificação do prompt, operações e parâmetros, corpus versionado e execução opcional com o provedor real.

## Comandos executados neste ambiente

Partindo da pasta `codegen/`:

```bash
# Resultado: 87 testes aprovados, sem carregar o conftest global.
PYTHONPATH=. pytest --noconftest -q tests/app/extracao/test_correcao.py

# Resultado: 103 testes aprovados (após revisão final).
# O shim de simplejson foi mantido FORA do projeto, somente para executar
# componentes determinísticos em ambiente que não tem todas as dependências.
PYTHONPATH=/mnt/data/t224_work/shims:. pytest --noconftest -q \
  tests/app/extracao/test_correcao.py \
  tests/app/extracao/test_corpus_reextracao_deterministico.py \
  tests/app/repositorio/test_rodadas_correcao.py \
  tests/app/graph/test_prompt_reextracao_t224.py \
  tests/app/core/test_metricas_t224.py

# Verificação vermelho → verde representativa: 1 falha contra o aplicador
# anterior à T-224; 24 casos aprovados após restaurar o aplicador novo.
PYTHONPATH=. pytest --noconftest -x -q tests/app/extracao/test_correcao.py \
  -k test_operacao_sem_trecho_literal_nao_altera_nada

# Não executado até o fim: bloqueado na preparação dos contratos.
make pre-commit
```

O comando `make pre-commit` parou em `poetry run python scripts/preparar_contratos.py`, pois **Poetry não está instalado** (`make: poetry: No such file or directory`, código 127). A tentativa de instalar dependências com o gerenciador disponível falhou por falta de acesso ao PyPI. **Ruff, mypy e a suíte completa não foram executados**, portanto o gate de PR ainda precisa ser validado no ambiente normal do projeto. A checagem sintática de Python (`compileall`), o parse do corpus JSON e `git diff --check` foram executados e aprovados.

## Validações e limitações

| Verificação | Situação |
| --- | --- |
| Aplicador, schema, trecho e lastro (incluindo regressões da primeira correção) | **Aprovada:** 87 testes sem shim |
| Corpus determinístico, cadeia com isolamento por job, prompt e contadores | **Aprovada:** 103 testes totais com shim temporário |
| Teste representativo primeiro falhando no código antigo e depois passando | **Aprovado:** 1 falha → 24 aprovações; não foi possível observar esse ciclo para cada teste novo |
| Registry do Prometheus consumido pelo `/metrics` | **Aprovada em teste isolado**, verificando as séries e os labels; endpoint HTTP completo não foi iniciado |
| Envelope de log frente a `contracts/observability/log.schema.json` | **Aprovada em teste isolado**; captura e validação dos logs da execução do grafo dependem da suíte completa |
| Grafo LangGraph com modelo falso e consumidor | **Testes criados, não executados**: faltam bibliotecas do projeto (LangGraph, Google GenAI, aio-pika e outras) |
| Banco PostgreSQL real e permissão `SELECT` | **Não executada**: dependente da infraestrutura; SQL de leitura validado com repositório falso |
| Corpus com modelo real | **Não executado**: `GOOGLE_API_KEY` não configurada, além de dependências ausentes; não há resultados do modelo real para reportar |
| `make pre-commit` | **Bloqueado por infraestrutura:** Poetry ausente |

## Para concluir o DoD no ambiente de desenvolvimento

```bash
cd codegen
poetry install
make pre-commit

# Corpus novo executado com o modelo real (exige GOOGLE_API_KEY válida):
poetry run pytest -q -m llm tests/app/extracao/test_corpus_reextracao.py

# Testes de integração com modelo falso, Prometheus /metrics e contrato de logs:
poetry run pytest -q tests/app/graph/test_reextracao.py

# Testes de histórico, corpus e código de conferência:
poetry run pytest -q tests/app/repositorio/test_rodadas_correcao.py \
  tests/app/extracao/test_correcao.py \
  tests/app/extracao/test_corpus_reextracao.py \
  tests/app/extracao/test_corpus_reextracao_deterministico.py \
  tests/app/graph/test_prompt_reextracao_t224.py \
  tests/app/core/test_metricas_t224.py
```

A verificação integral da funcionalidade **não pode ser afirmada** enquanto a suíte do grafo, o gate `pre-commit` e os casos reais do corpus estiverem pendentes.
