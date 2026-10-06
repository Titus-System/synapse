# T-218 — Consumo de parâmetros confirmados

Base: `synapse-commit(2).zip`, branch `develop`, commit `abd10ccdfa4f26a09723a847b0eb391923e977c2`.

Implementação e testes automatizados concluídos. **A validação com RabbitMQ real está pendente**: a tentativa falhou na preparação do ambiente por ausência de Docker, antes de publicar qualquer mensagem. O DoD não deve ser marcado integralmente como concluído até essa execução local.

## 1. Branch, aplicação e commit

Na raiz do seu repositório, com as alterações anteriores já guardadas:

```bash
git status --short
git switch develop
git pull --ff-only origin develop
git switch -c feature/t-218-parametros-confirmados
```

O pacote contém os arquivos completos nos caminhos originais e `T-218.patch`. Use uma das formas:

- Copiar os arquivos `codegen/` e `docs/` para os mesmos caminhos do projeto, se a base ainda corresponde ao ZIP analisado.
- Se a `develop` avançou, extrair o pacote fora do repositório, por exemplo em `../T-218`, e aplicar o patch. Isso detecta incompatibilidades em vez de sobrescrever trabalho integrado depois:

```bash
git apply --check ../T-218/T-218.patch
git apply ../T-218/T-218.patch
```

Se o check apontar conflito, concilie os trechos com a versão nova. T-204, T-211 e T-221 compartilham arquivos desta entrega; não substitua essas implementações pelos arquivos completos da base antiga. Não copie os arquivos completos e aplique o patch em seguida: são alternativas.

Depois de aplicar:

```bash
cd codegen
poetry install
make pre-commit
make lint
cd ..
docker compose -f deploy/docker-compose.yml up -d rabbitmq
cd codegen
make test-rabbitmq
cd ..
git diff --check
git diff --stat
git add codegen docs/ARCHITECTURE.md
git diff --cached
git commit -m "feat(codegen): consome parâmetros confirmados por versão" -m "Review: auto"
git push -u origin feature/t-218-parametros-confirmados
```

Abra o PR para `develop`. O trailer `Review: human` só substitui `auto` depois de uma pessoa ler e aprovar o diff. Confira que o staging contém apenas esta tarefa. Nenhuma branch, commit, publicação ou push foi realizado durante esta implementação.

## 2. Comportamento entregue

| Entrada/situação | Resultado |
| --- | --- |
| Confirmação com competências e orçamento | Abre `job_id:regra_id` em `load_rule`; delega os valores exatos ao worker pelos nós existentes |
| Outra versão do mesmo job | Abre outra thread; preserva a anterior |
| Reentrega após fim | ACK, sem repetir modelo, artefatos ou publicações |
| Reentrega durante espera pelo worker | ACK, sem delegar novamente; continua esperando o resultado |
| Checkpoint incompleto após falha transitória | Continua sem repetir nós já concluídos |
| Sem competências | `ContextoAusenteError`, reject sem requeue, causa `contexto_ausente`, sem publicar erro do job |
| Sem orçamento | O ciclo começa; `dispatch_execution` produz a falha permanente existente |
| Job encerrado, com limpeza pendente ou concluída | ACK sem abrir ciclo, inclusive confirmação antiga sem competências |
| JSON/schema inválido | Reject sem requeue antes do grafo |
| Falha permanente do ciclo | `etapa-alterada` com `erro`, depois reject sem requeue |
| Falha transitória | NACK com requeue |

O estado inicial não preenche `origem`. O orçamento permanece decimal exato. Não foram alterados contratos compartilhados, API, worker, dependências, migrations, nós ou arestas. Não foi acrescentado `interrupt()` nem consulta a `jobs` para obter contexto.

## 3. Arquivos

| Arquivo | Tipo | Mudança |
| --- | --- | --- |
| `codegen/app/contratos/mensagens.py` | Modificado | Campos opcionais em `ParametrosConfirmados` |
| `codegen/app/mensageria/broker.py` | Modificado | Registro do consumer com schema `parametros-confirmados` |
| `codegen/app/mensageria/roteamento.py` | Modificado | Estado confirmado, ramo real, exceção própria, bloqueio de job encerrado e resultado do consumo |
| `codegen/app/mensageria/consumers.py` | Modificado | Reject sem requeue para contexto ausente; logs e contagem dos descartes |
| `codegen/app/graph/entrypoint.py` | Modificado | `RunOutcome` diferencia avanço de nó e reentrega sem avanço; mantém o guard existente |
| `codegen/app/core/metrics/global_metrics.py` | Modificado | Contador com três resultados fechados |
| `codegen/app/main.py` | Modificado | Carga explícita dos coletores na composição |
| `codegen/tests/app/confirmacao_falsa.py` | Novo | Banco/modelo/produtores falsos; fluxo de aplicação real |
| `codegen/tests/app/graph/test_parametros_confirmados.py` | Novo | 21 casos de comportamento, schema, correlação, logs e métricas |
| `codegen/tests/app/graph/test_entrypoint.py` | Modificado | Confere retorno de processamento e reentrega finalizada |
| `codegen/tests/app/test_mensageria.py` | Modificado | Exige o quarto consumer e a fila correta |
| `codegen/tests/app/test_roteamento.py` | Modificado | Substitui expectativa obsoleta de `NotImplementedError` por descarte de contexto |
| `codegen/tests/app/test_rabbitmq_integracao.py` | Modificado | Exige consumo e profundidade zero com mensagens válidas, duplicadas e inválidas |
| `codegen/README.md` | Modificado | Documenta consumidor ativo |
| `codegen/docs/mensageria.md` | Modificado | Decisões de consumo e semântica de observabilidade |
| `codegen/docs/retomada-apos-execucao.md` | Modificado | Abertura por confirmação e proteção após encerramento |
| `docs/ARCHITECTURE.md` | Modificado | Atualiza estado implementado e catálogo da mensagem |
| `codegen/docs/t-218-verificacao.md` | Novo | Este relatório |

## 4. Verificações executadas

Ambiente: Python 3.12.14, dependências fixadas em `codegen/requirements-dev.txt`, compatíveis com o lock fornecido. Poetry instalado no ambiente temporário. `psycopg-binary==3.3.6` foi instalado apenas nesse ambiente por ausência de `libpq`; os manifests do projeto permaneceram iguais.

Os comandos abaixo foram executados em `codegen/`, salvo indicação:

| Comando | Resultado |
| --- | --- |
| `make pre-commit`, antes das alterações | 436 aprovados, 28 pulados; Ruff e mypy aprovados |
| `poetry run pytest tests/app/graph/test_parametros_confirmados.py -q`, antes da implementação | 13 falhas e 8 aprovados: abertura, descarte, reentrega, encerramento, falhas e métrica ainda não atendidos |
| `make pre-commit`, após implementação | **457 aprovados, 28 pulados**; Ruff aprovado, formatação aplicada, mypy sem erros em 64 arquivos |
| `make lint` | Ruff aprovado; Bandit sem achados |
| `git diff --check`, na raiz | Aprovado |
| `RUN_RABBITMQ_INTEGRATION=1 poetry run pytest -p no:cacheprovider tests/app/test_rabbitmq_integracao.py -k parametros_confirmados -x -q` | **Bloqueado na fixture:** `FileNotFoundError: docker`; 1 erro de preparação, 9 casos não selecionados |

A primeira preparação do gate encontrou ausência de `libpq`; depois da instalação local de `psycopg-binary`, a execução original e a final passaram. Também foi tentada a preparação de RabbitMQ via `apt-get update`, bloqueada por permissões de usuário/grupo do ambiente. Não houve broker instalado ou simulação apresentada como broker real.

Os 28 testes pulados são integrações já condicionais do projeto: 10 de RabbitMQ, 16 de PostgreSQL e 2 de provedor LLM. Não foram adicionados skips para ocultar falhas.

### Evidências do caminho real

- `Consumer.receber → GraphRouter.entregar → run_to_completion → run → build_graph`: nenhum desses componentes é mockado. Checkpoints usam `InMemorySaver`; banco, consulta da regra, modelo e produtores são substituídos pelas fronteiras falsas de teste.
- As publicações produzidas pelos nós são serializadas e validadas contra os schemas oficiais; o teste confere a sequência e o comando final.
- Reentregas na pausa e depois do fim preservam as linhas gravadas e a lista completa de publicações, sem segunda chamada ao modelo.
- A falha transitória no armazenamento do código reenfileira e depois continua; prompt e resposta já concluídos não são repetidos.
- Falhas permanentes por código inválido e orçamento ausente produzem o erro na etapa correta, sem delegação ao worker.
- Os logs passam por `ManipuladorFilaContexto.prepare` e `FormatadorJson`, na mesma sequência de serialização da aplicação, e são validados contra `contracts/observability/log.schema.json`. São conferidos sucesso, reentrega, contexto ausente e falhas permanentes, sem conteúdo de regra/código. Dois jobs consecutivos não compartilham correlação; o contexto anterior também é restaurado.
- `GET /metrics` é exercitado pela aplicação ASGI real. O contador `codegen_parametros_confirmados_total` aumenta `+1` em cada um dos três resultados após consumir sucesso, duplicata e mensagem sem contexto. A reentrega após fim aumenta apenas `reentrega_ignorada`; falha permanente aumenta apenas `descartada`. Todas as amostras têm somente o label `resultado`.

### Semântica da métrica

`ciclo_aberto` conta entregas que avançaram o grafo até pausa/fim, incluindo continuação bem-sucedida de um checkpoint incompleto. `reentrega_ignorada` conta entregas sem nova execução de nó. `descartada` conta descartes definitivos; a causa específica fica no log. É um contador de resultados de mensagens, não de jobs únicos. Tentativas transitórias reenfileiradas e cancelamentos não são contados como conclusões.

## 5. Pendências de ambiente e integração

- **RabbitMQ real:** executar `make test-rabbitmq` com Docker e o broker do compose disponíveis. O teste da T-218 publica cinco mensagens (válida, antiga sem contexto, schema inválido, duplicata e JSON malformado), aguarda os callbacks reais e exige um consumer, profundidade zero e apenas uma delegação.
- **PostgreSQL real/checkpointer durável:** não verificado nesta execução; testes usaram banco falso e checkpoint em memória.
- **LLM real, build da imagem, fluxo entre API/codegen/worker e coleta externa Prometheus/Grafana:** não executados. O teste de `/metrics` comprova o registry/endpoint, não a coleta pelo painel.
- **T-217:** integrar próximo desta tarefa. Enquanto a API enviar confirmações sem competências, elas serão consumidas e descartadas com `contexto_ausente`, conforme decisão da tarefa.

O patch foi preparado sobre o commit indicado no início. A CI e a validação com RabbitMQ real continuam necessárias antes de considerar o DoD completo.
