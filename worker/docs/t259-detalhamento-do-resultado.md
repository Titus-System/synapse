# T-259 — detalhamento do resultado e totais absolutos da decomposição

O harness já devolvia os agregados do período. Esta entrega acrescenta duas coisas, das mesmas parcelas em centavos: as **três quebras absolutas** da decomposição (`matricula`, `loja_absoluto`, `competencia_absoluto`), que distribuem o total simulado em vez da diferença, e o **detalhamento**, uma linha por competência e matrícula, gravado em `resultados_simulacao.linhas`.

É o nível 2 da explicabilidade (`docs/ARCHITECTURE.md` §3.3) descendo até a pessoa: o mesmo gestor que confere o número, depois de "quanto mudou" e "por causa de quê", quer ver quem receberia quanto. Nada disso exige algo novo da função gerada — o código e o prompt de geração não mudam; é agregação do harness sobre `apuracao_simulada` e `contribuicoes`, que ele já recebia.

## Onde está

| Arquivo | O quê |
| --- | --- |
| `app/sandbox/resultado.py` | `_decompor` ganha as três quebras absolutas; `_detalhar` monta o detalhamento; `montar_resultado` devolve `ResultadoMontado(resultado, linhas)` |
| `app/sandbox/envelope.py` | o envelope passa à **versão 3**, com `linhas` ao lado de `resultado` |
| `app/sandbox/harness.py`, `app/sandbox/executor.py` | levam o detalhamento do agregador ao envelope |
| `app/execucao/schema.py` | `validar_linhas`: forma contra `resultado-linhas.schema.json` e as competências do comando |
| `app/execucao/coleta.py` | `DesfechoClassificado.linhas`; a recusa é `resultado_fora_do_schema`; a métrica do tamanho do envelope |
| `app/execucao/registro.py` | `LinhaDoResultado.linhas`, só em `sucesso` |
| `app/repositorio/resultados.py` | `linhas` no mesmo `INSERT` do resultado |
| `app/core/metrics/global_metrics.py` | `sandbox_envelope_bytes` |

Contratos: `resultado-decomposicao.schema.json` (as três quebras, opcionais) e `resultado-linhas.schema.json` (o detalhamento). Nenhum dos dois foi alterado aqui — a T-200 C e a T-256 os fixaram, e a coluna veio da T-258 (migration 021, que não exigiu permissão nova: o worker já tem `INSERT` na tabela).

## Os números fecham por construção, não por conferência

Tudo sai das mesmas parcelas em centavos que os totais já usavam. A comissão de cada matrícula e competência é arredondada **uma vez**, como a T-032 faz ao congelar o baseline, e por isso somar o detalhamento, ou qualquer uma das três quebras absolutas, dá exatamente `totais.simulado`.

A reconciliação do resíduo de arredondamento das contribuições acontece **uma vez**, em `_parcelas_por_linha`, e a quebra por elemento e o detalhamento leem o mesmo resultado dela. Antes desta entrega o cálculo vivia dentro de `_por_elemento`; recalculá-lo em dois lugares abriria a porta para a quebra por elemento e o detalhamento divergirem em um centavo na mesma linha. Daí também que a soma das `contribuicoes` de uma linha seja igual à `diferenca` dela, sem sobra.

Uma matrícula aparece **uma vez por mês**, com a marca, a loja e o cargo da lotação no RH naquele mês — os do baseline. Venda em outra marca ou loja (a MATRIC-422 em agosto de 2025) fica consolidada nessa mesma linha. As dimensões nunca vêm da apuração simulada: assim o código gerado não consegue mover uma matrícula de loja e distorcer a quebra.

## Por que o detalhamento é um campo próprio do envelope

`resultado` é gravado nas colunas que `GET /jobs/{id}` devolve. O detalhamento do período inteiro são 503 KiB, contra 14 KiB do resultado: dentro de `resultado` ele faria a consulta do job carregar o período inteiro de todas as simulações. Fica num campo irmão no envelope e numa coluna própria, que só a rota de detalhamento (T-260) lê.

O teto do stdout do container é 1 MiB (`Limites.teto_stdout`). Medido com uma regra de três elementos que altera todas as matrículas das cinco competências:

| | tamanho |
| --- | --- |
| envelope inteiro | 517 KiB — **51%** do teto |
| `linhas` | 503 KiB (2.672 linhas em 5 competências) |
| `resultado` | 14 KiB |

O envelope é serializado sem espaços, e dois testes conferem a folga: um monta o envelope no host, outro o produz na imagem real. Se um dia não couber, o teto se ajusta em `app/execucao/container.py`, conferindo que a memória do container comporta o novo valor — não se corta o detalhamento.

## O que vem do container não se recompõe, e não se confia nele

O worker grava o detalhamento **como veio**, igual à decomposição. Ele confere forma e período, não aritmética: o schema, e que as competências de `linhas` são exatamente as do comando (`competencias_divergentes`). A conferência dos valores contra o baseline e os totais é da **T-262**.

Duas consequências de `linhas` ser dado não confiável:

- **O caminho do problema é estático.** As chaves de `linhas` são competência e matrícula escolhidas pelo container, então o caminho do validador não pode chegar ao diagnóstico nem ao log: `validar_linhas` o descarta e devolve sempre `$.linhas` com a palavra-chave que reprovou. Um teste põe `CONTEUDO-PRIVADO` como chave e como valor e exige que ele não apareça no `repr` do desfecho, no log nem no diagnóstico gravado.
- **A classificação roda numa thread.** Conferir o envelope contra os schemas é CPU pura e cresce linearmente com o detalhamento: perto de **1 s** no período inteiro, contra 22 ms do resultado sozinho, e cerca de 4 s com o stdout no teto, cheio de chaves inválidas (medidos 2,9 s para 65 mil chaves em 693 KiB). No event loop isso pararia o heartbeat do RabbitMQ e o `/metrics` por todo esse tempo, então `_processar` chama `classificar` por `asyncio.to_thread`, como já faz com o container. O contexto do job acompanha a thread, e o log da recusa continua correlacionado, o que um teste do consumidor confere.

Um detalhamento malformado, ou um envelope de `sucesso` **sem** detalhamento, é `erro_codigo` com motivo `resultado_fora_do_schema`, como um resultado malformado. O harness e o worker são construídos e implantados juntos, então um sucesso sem detalhamento é sempre defeito; a ausência é tratada na validação do resultado, e não como `envelope_invalido`, para que o codegen leia no diagnóstico **o que** faltou.

Fora de `sucesso`, a coluna é nula. `linha_do_julgamento` levanta `ValueError` se um sucesso chegar sem detalhamento validado: a coleta já garante que isso não acontece, e gravar pela metade seria pior.

## O que esta entrega deixa em aberto

O custo da validação é de ~0,4 ms por combinação de competência e matrícula, e vem da travessia dos `$ref` de `comum.schema.json`, sete por linha. A thread tira isso do event loop, mas não o reduz: o dataset atual tem 2.672 combinações, e num bem maior a conferência passa de alguns segundos por execução. Se isso incomodar, as saídas são achatar o schema do detalhamento, que é mudança de contrato, ou escrever a conferência da linha à mão em vez de pelo validador — nenhuma das duas cabia aqui.

## Observabilidade

| Sinal | O quê | Pergunta que responde |
| --- | --- | --- |
| log `resultado gravado` | ganha `competencias_detalhadas` e `linhas_detalhadas` (contagens, nunca conteúdo) | o detalhamento gravado tem o tamanho esperado para o período? |
| log `detalhamento recusado` | a classe do que reprovou, em `classes` | por que a coleta recusou o detalhamento? |
| métrica `sandbox_envelope_bytes{status}` | histograma do stdout do envelope, com buckets até 1 MiB (943718 = 90% do teto) | quão perto do teto do stdout o envelope está? |

A métrica é observada **uma vez por envelope reconhecido**, com o `status` do envelope, mesmo quando o detalhamento é recusado depois: a pergunta é sobre o tamanho do que o container escreveu, não sobre o desfecho. Sem envelope válido (timeout, OOM, saída cortada, infra) não há status a atribuir e nada é observado — o estouro do teto aparece como desfecho `saida_truncada`, não no histograma. Uma reentrega que só republica o evento não executa o sandbox e não observa de novo.

## Verificação

Na pasta `worker/`, com `postgres`, `rabbitmq` e o Docker de pé:

```bash
poetry run pytest tests/app/sandbox/test_resultado_linhas.py        # quebras absolutas, detalhamento, teto do stdout
poetry run pytest tests/app/execucao/test_linhas.py                 # detalhamento malformado na coleta
poetry run pytest tests/app/execucao/test_linhas_integration.py     # imagem real, e a métrica em /metrics
poetry run pytest tests/app/repositorio/test_resultados.py          # Postgres: a coluna, e nula sem sucesso
sh verify.sh
poetry run python -m scripts.build_baselines --check
make e2e
```

`resultado.py` **não** entra no hash do motor que congela os baselines, e nenhum dos arquivos que entram (`regras_base.py`, `assercoes.py`, `ajustes_competencia.py`, `regras_competencia.py`, `scripts/build_baselines.py`) foi alterado: `build_baselines --check` continua passando e os cinco baselines congelados não mudam.
