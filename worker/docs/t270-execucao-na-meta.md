# T-270: a execução na meta de venda

Com `meta_venda` em `executar-codigo`, a regra é simulada como se as vendas do período tivessem atingido a meta. O harness multiplica o `vlr_venda` de toda venda das competências do job pelo mesmo fator, `meta_venda / total histórico`, reapura o baseline sobre as vendas escaladas e só então chama a função gerada. A função não muda e não sabe da meta: recebe `bases["vendas"]` e `apuracao_base` escalados, no formato de sempre. Sem `meta_venda`, nada disso acontece, e a execução é byte a byte a de antes do campo (o payload nem leva a chave).

A escala vale para a entrada, nunca para os totais depois da execução: a apuração não é linear nas vendas (piso de afastamento, arredondamento por linha). Em novembro, com a meta 10% acima das vendas históricas, o baseline reapurado é R$ 558.870,26, e não 1,1 vez o congelado (R$ 559.220,55).

## Onde está

| Arquivo | O quê |
| --- | --- |
| `app/sandbox/escalonamento.py` | total histórico, fator, escala das vendas e reapuração do baseline; só stdlib, roda nos dois lados |
| `app/sandbox/carga.py` | com meta, troca as vendas pelas escaladas e o baseline congelado pelo reapurado |
| `app/sandbox/executor.py`, `app/sandbox/envelope.py` | `meta_venda` é o único campo opcional do payload (`CAMPOS_PAYLOAD_OPCIONAIS`) |
| `app/execucao/bases.py` | as bases que o worker mantém, a reapuração do baseline na meta e `vendas_historicas` |
| `app/execucao/veredito.py` | na meta, confere o baseline do container contra o que o worker reapurou |
| `app/repositorio/resultados.py` | grava `meta_venda` e `proposito`, e a reentrega é por código, meta e propósito |
| `worker/sandbox/Dockerfile` | a imagem do sandbox passa a levar `regras_competencia.py`, `escalonamento.py` e `regras_competencia.jsonl` |
| `worker/Dockerfile` | a imagem do worker passa a levar as bases da apuração |

## Os números

- **Total histórico** (`totais.vendas_historicas`): a soma de `vlr_venda` de todas as vendas das competências do job, em todas as lojas, marcas e cargos, arredondada a centavos. É o mesmo valor que divide a meta, então uma meta igual a ele escala por exatamente 1 e reproduz o baseline congelado. Para 2025-08 e 2025-11, R$ 23.583.194,87, o valor do exemplo do contrato.
- **Venda escalada**: `float(Decimal(str(vlr_venda)) * fator)`, sem arredondar a centavos, para não mudar a proporção entre as vendas.
- **Baseline na meta**: `apurar_vigente` (`regras_competencia.py`) competência a competência, com o catálogo `regras_competencia.jsonl`, `eventos_rh` inteira e cada linha publicada como `scripts/build_baselines.py` a publica. Sobre as vendas históricas, reproduz os cinco baselines congelados linha a linha.

Os arquivos do manifesto dos baselines (`regras_base.py`, `assercoes.py`, `ajustes_competencia.py`, `regras_competencia.py`, `build_baselines.py`) não mudam: `escalonamento.py` só os chama, e `build_baselines --check` continua verde.

`cod_marca` de cada linha não vem do RH direto: vem de `rastreabilidade.chaves_comissao`, como `build_baselines._linhas_apuracao_base` extrai para o congelamento, e `escalonamento.py` confere que ela bate com o RH. Uma matrícula com vendas em mais de uma marca no mês não teria uma única `cod_marca` para a coluna, e isso nunca ocorreu nas competências já congeladas (o congelamento recusaria); a escala não cria esse caso, porque não muda em quais marcas cada pessoa vendeu, só o valor.

## A conferência do baseline na meta

Na meta não há total congelado. O código gerado roda no mesmo processo do harness e alcança o baseline que ele guarda (o ataque pelo `gc` dos testes infla esse baseline e inventa uma economia que reconcilia). Por isso o worker reapura o mesmo baseline **no próprio processo**, sobre a própria cópia das bases, e é esse total que confere o `totais.baseline` devolvido, com a mesma conta de `_totais_conferem`. A regra não alcança esse processo.

- O worker guarda `rh`, `vendas`, `comissoes`, `eventos_rh` e `regras_competencia.jsonl`, conferidos na subida contra o sha256 que o manifesto dos baselines registra em `fontes_sha256`. Sem eles, ou com um deles alterado, o worker não sobe.
- A reapuração usa só a stdlib, então o processo do worker continua sem pandas e sem o harness (`test_isolamento_harness.py`).
- Ela roda numa thread, **antes** do container. Uma meta que não se aplica às bases (competência fora delas, escala que estoura o float) leva o comando à DLQ sem subir o container: a regra nem rodou, e a falha não é dela.
- O container faz a mesma reapuração com o mesmo código sobre os mesmos dados, e por isso chega ao mesmo centavo. Uma divergência é adulteração ou descompasso entre as imagens, e sai `erro_codigo` com `baseline_divergente`.

O orçamento continua fora do container: a meta entra porque muda a entrada da apuração, não o critério de julgamento. O veredito, quando há orçamento, compara o simulado na meta. Uma execução na meta sem orçamento sai sem veredito (T-281).

`totais.vendas_historicas` vai em todo sucesso, com ou sem meta, lido das bases do worker. Um `totais.vendas_historicas` na saída do container é reprovado com `fornecido_pelo_container`, como o `totais.orcamento`.

## Custo

| Etapa | 1 competência | 5 competências |
| --- | --- | --- |
| reapuração no worker, por execução na meta | 0,12 s | 0,6 s |
| processamento no container, sem meta | 0,15 s | 0,27 s |
| processamento no container, com meta | 0,29 s | 1,05 s |
| pico de memória do container, sem meta | 80 MiB | 89 MiB |
| pico de memória do container, com meta | 86 MiB | 106 MiB |

O processamento no container é o `processar` do executor, sem a subida do container (cerca de 1 s a mais, em parede). O pior caso do dataset, com as cinco competências na meta, leva cerca de 2 s em parede, abaixo de 5 % do prazo de 60 s, e chega a 41 % do limite de 256 MiB, então os limites de `Limites` não mudam. A carga das bases na subida do worker leva 0,6 s e retém cerca de 30 MiB.

## Meta, propósito e reentrega

`meta_venda` e `proposito` do comando são gravados em `resultados_simulacao` em qualquer desfecho, inclusive o `erro_infra` esgotado. O evento leva `meta_venda` quando a execução teve meta, e `proposito` só quando é `busca_meta`, porque ausente equivale a `simulacao`. Os dois saem em qualquer status: a api separa a candidata da busca antes de olhar o desfecho (T-274).

A reentrega reconhece o mesmo comando por job, código, meta e propósito. A busca da meta maior (T-273) roda o mesmo código em várias metas candidatas, e cada candidata é uma execução com a própria linha. A consulta compara a meta com `IS NOT DISTINCT FROM`, então um comando sem meta só encontra a linha sem meta.

Só a ausência de `meta_venda` é uma execução sobre as vendas históricas: um `"meta_venda": null` explícito, zero, negativo ou não finito é recusado e vai à DLQ, porque rodaria nas vendas históricas uma execução pedida na meta.

## Observabilidade

| Sinal | O quê |
| --- | --- |
| `execução preparada` | `com_meta_venda` e `proposito`, nunca o valor da meta |
| `baseline na meta reapurado` | `duracao_s` da reapuração no worker |
| `baseline na meta não reapurado; encaminhando para DLQ` | só a classe da falha, em `erro` |
| `execução julgada`, `resultado gravado` | `com_meta_venda` e `proposito` |
| `worker_execucoes_na_meta_total{proposito, desfecho}` | execuções julgadas na meta; a reentrega que só republica não conta, e cada tentativa de `erro_infra` conta |
| `worker_baseline_na_meta_seconds{resultado}` | duração da reapuração no worker, `ok` ou `falha` |

As execuções na meta também contam em `worker_execucoes_julgadas_total`. A meta não é rótulo: é um valor contínuo, e cada candidata da busca abriria uma série.

## Verificação

```bash
poetry run pytest tests/app/sandbox/test_escalonamento.py tests/app/execucao/test_bases.py
SANDBOX_IMAGE_TESTE=synapse-sandbox:test poetry run pytest -m docker tests/app/execucao/test_execucao_na_meta_integration.py
poetry run pytest -m e2e tests/e2e -k meta
```
