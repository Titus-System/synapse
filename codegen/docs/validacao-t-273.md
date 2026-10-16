# Validação da T-273

Verificação local em 12/10/2026, sobre `develop` em `f17079e`, com as alterações da T-273 ainda sem commit. Este registro reúne os resultados para a descrição do PR; nenhum PR foi aberto ou atualizado nesta execução.

## Implementação

Busca determinística da meta com até 12 candidatas e tolerância relativa de 0,1%, mantendo código, orçamento e competências. O checkpoint identifica cada execução por código, propósito e meta; reentregas antigas não avançam a candidata pendente. A conclusão publica `meta-venda-sugerida` com o resultado vencedor ou um motivo de ausência de solução, e auditoria de `decisao` com identidade própria. A configuração `BUSCA_META_ENABLED=false` preserva a desativação até a integração da T-274.

O algoritmo, o tratamento do limite, a precisão numérica e a justificativa baseada no teto de 60 segundos do sandbox estão em [busca-meta.md](busca-meta.md). Não houve alteração de schema compartilhado, migration, API, worker ou frontend. A edição previamente existente em `docs/validacao-t-275.md` foi preservada.

## Comandos e resultados

Executados em `codegen`, exceto `git diff --check`:

| Comando | Resultado |
| --- | --- |
| `make graph` | Diagrama regenerado e conferido pelo teste de topologia |
| `GOOGLE_API_KEY= make pre-commit` | Ruff, formatação e mypy aprovados; **714 testes passaram, 48 pulados**, em 33,25 s |
| `RUN_RABBITMQ_INTEGRATION=1 RUN_POSTGRES_INTEGRATION=1 GOOGLE_API_KEY= make test-rabbitmq` | **17 passaram, 2 pulados, 743 desmarcados**, em 125,53 s |
| `RUN_RABBITMQ_INTEGRATION=1 RUN_POSTGRES_INTEGRATION=1 poetry run pytest -q tests/app/test_busca_meta_integracao.py` | **5 passaram**, em 72,39 s |
| `poetry run pytest -q tests/app/graph/test_busca_meta.py tests/app/test_busca_meta.py` | **33 passaram**, em 15,22 s |
| `poetry run bandit -r app/` | Nenhum achado |
| `git diff --check` | Sem problemas de whitespace |

O primeiro gate encontrou o teste de topologia anterior à T-273, que ainda esperava o conjunto antigo de nós e arestas. A expectativa foi atualizada para o fluxo planejado, mantendo a comparação exata, e o gate completo passou na segunda execução.

Duas verificações por mutação comprovaram que os testes detectam as garantias: remover a rejeição de não monotonicidade fez o teste correspondente falhar; remover a comparação da meta na retomada fez o teste aceitar indevidamente um resultado divergente e falhar. As alterações temporárias foram restauradas byte a byte antes do gate final.

## Integração e observabilidade

A integração criou um PostgreSQL descartável com as migrations existentes da API, consultado com o usuário do codegen, e usou `AsyncPostgresSaver` real. Cada caso declarou um vhost exclusivo no RabbitMQ existente e o removeu ao terminar, sem consumir filas de desenvolvimento. Os consumers, router, nós e producers são os reais; os resultados do worker são fixtures persistidas pelo teste antes de publicar `simulacao-concluida`.

Foram verificados sucesso, `nao_monotonica`, `intervalo_esgotado`, `falha_execucao`, sequência de candidatas, duplicatas antigas e duas retomadas concorrentes. A concorrência publicou apenas uma candidata. Os payloads de execução, sugestão e auditoria foram conferidos contra os schemas. Cada retomada abre uma nova conexão de checkpoint, demonstrando independência de estado em memória.

Os testes do grafo conferiram os logs serializados de início, envio, recebimento e conclusão contra `contracts/observability/log.schema.json`, os campos `job_id`/`no`, a ausência de valores financeiros nos campos emitidos e a restauração da correlação. Os contadores de desfecho e histogramas de processamento/espera foram observados no registry exposto por `/metrics`; o teste com banco e broker reais também conferiu o incremento do desfecho e uma amostra de espera por candidata.

## Limites da verificação

- Os testes opcionais de LLM não chamaram o provedor: o gate foi executado com `GOOGLE_API_KEY` vazia. A busca não chama LLM; os testes impedem essa chamada.
- Os dois cenários ponta a ponta opcionais da suíte RabbitMQ foram pulados. Não foi executado um worker real com sandbox nem uma geração completa iniciada pela API. A integração da busca representa o worker externo com resultados controlados.
- Não foi verificada a coleta externa no Prometheus/Grafana, nem a interface ou aceitação da meta, que pertencem à T-274/T-276.
- A feature não foi ativada no ambiente. CI, commit, push e PR não foram executados.

## Correção da precisão após revisão

Removido o arredondamento das candidatas para centavos e o piso absoluto do critério de parada. A candidata é canonicalizada na representação decimal do `float` que o worker recebe, preservando sua identidade na retomada. Dois testes de regressão falharam antes da correção: margem pequena na estimativa proporcional e bisseção entre metas separadas por um centavo. Um terceiro teste percorre o grafo e confere a sugestão com a referência da execução fracionária viável; sua fixture reproduz a conversão numérica do worker.

`GOOGLE_API_KEY= make pre-commit` passou na versão final: **717 passaram, 48 pulados**, em 54,22 s, com Ruff, formatação e mypy aprovados. A suíte `RUN_RABBITMQ_INTEGRATION=1 RUN_POSTGRES_INTEGRATION=1 GOOGLE_API_KEY= poetry run pytest tests/app/test_busca_meta_integracao.py -q` também passou: **5 passaram**, em 56,84 s. Ela foi executada após remover o arredondamento, antes do ajuste final de canonicalização; o cenário fracionário foi verificado pelo grafo em memória. As verificações existentes de logs e métricas em `/metrics` continuam verdes. Nenhum worker real ou provedor LLM foi chamado nesta correção.
