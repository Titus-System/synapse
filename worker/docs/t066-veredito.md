# T-066: conferência contra o baseline e veredito de orçamento

Depois de o container devolver o resultado e a T-065 o classificar, o processo do `worker`,
fora do container, faz seis coisas, nesta ordem:

1. **confere** o `totais.baseline` que saiu do container contra o baseline congelado (T-032)
   que o worker lê por conta própria, e que os totais fecham entre si;
2. **confere o detalhamento** (T-262): linha a linha contra o mesmo baseline, e a coerência entre
   o detalhamento, os totais e as quebras da decomposição (seção "A conferência do detalhamento");
3. com isso, **a diferença** absoluta e percentual do container passam a ser as do baseline do
   worker, e seguem como vieram, sem recomposição;
4. quando o comando trouxe `elementos_exigidos`, **confere a cobertura** dos elementos da regra
   (T-241, `docs/t241-conferencia-de-cobertura.md`);
5. quando o comando trouxe `alcance`, **confere o escopo**: fora do alcance da regra, a comissão
   simulada é a do baseline (`docs/conferencia-de-escopo.md`);
6. **aplica o orçamento** e emite o veredito, quando o comando trouxe orçamento.

O orçamento é o único parâmetro que **julga** o resultado, e nunca entrou no container: código
gerado que o enxergasse poderia mirar nele.

Um job sem orçamento (T-281) recebe `executar-codigo` sem o campo. As conferências 1 a 5 são as
mesmas, e só a 6 não acontece: o `sucesso` sai sem veredito e sem `totais.orcamento`, porque não
há critério que o julgue. Um baseline adulterado continua `baseline_divergente`, e uma cobertura
incompleta continua `cobertura_incompleta`.

Numa execução na meta de venda (T-270), não há baseline congelado da meta: as conferências 1 e 2 são contra o baseline que o próprio worker reapurou sobre as vendas escaladas, linha a linha, antes de subir o container (`app/execucao/bases.py`). As conferências 3 a 5 são as mesmas, e o veredito compara o simulado na meta com o orçamento. Todo `sucesso`, com ou sem meta, leva `totais.vendas_historicas`, lido das bases do worker e nunca do container. Detalhes em `docs/t270-execucao-na-meta.md`.

## Onde está

| Arquivo | O quê |
| --- | --- |
| `app/execucao/baseline.py` | `carregar_baselines`: os cinco baselines congelados, totais e linhas, conferidos contra o manifesto |
| `app/execucao/conferencia.py` | `conferir_detalhamento`: o detalhamento contra o baseline e a coerência com os totais e as quebras (T-262) |
| `app/execucao/bases.py` | `carregar_bases`: as bases da apuração, para o baseline na meta e `vendas_historicas` (T-270) |
| `app/execucao/veredito.py` | `julgar`, `decidir_veredito`, `Julgamento` |
| `app/mensageria/consumidor.py` | classifica (T-065), julga e registra classe, motivo e veredito no log |
| `app/main.py` | `carregar_baselines()` e `carregar_bases()` na subida: sem eles, o worker não sobe |
| `worker/Dockerfile` | copia `sandbox/data/domrock/baselines/` (os cinco `.jsonl` e o manifesto) e as bases da apuração |
| `docs/decisoes/dec-093.md` | a decisão do caso de igualdade e do `indeterminado` |

## O veredito

| Total simulado do período | Veredito |
| --- | --- |
| menor que o orçamento | `viavel` |
| **igual ao orçamento** | `viavel` (DEC-093) |
| maior que o orçamento | `inviavel` |

O veredito confronta o **total absoluto**, e não a diferença contra o baseline: é o total que o
orçamento limita. A comparação é em `Decimal` a partir da representação de cada número, sem
arredondar o orçamento.

**`indeterminado`** é o veredito de todo desfecho que não é `sucesso`: asserção violada,
`erro_codigo` (inclusive a divergência contra o baseline) e `erro_infra`. Sem número confiável
não há julgamento, e falha de cálculo nunca é inviabilidade. Um `sucesso` sai `viavel` ou
`inviavel` quando há orçamento, e sem veredito (`None`) quando não há, nunca `indeterminado`.

### Correspondência com o contrato (para a T-067)

`simulacao-concluida.schema.json` e `resultados_simulacao.veredito` declaram o veredito
ausente/nulo quando o status não é `sucesso`, e o contrato **não** foi alterado. A T-067 mapeia:

| `Julgamento.classe` | `veredito` interno | Na gravação e no evento |
| --- | --- | --- |
| `sucesso` | `viavel` ou `inviavel` | o mesmo |
| `sucesso` de job sem orçamento | `None` | **nulo/ausente**, e `totais.orcamento` ausente |
| `assercao_violada`, `erro_codigo`, `erro_infra` | `indeterminado` | **nulo/ausente** |

A `api` lê `sucesso` sem veredito como o resultado de um job sem orçamento, que vai à decisão do
usuário e pode ser liberado e salvo como uma regra viável (T-281).

A `api` já trata esses status como `ERRO` pelo status, e lê `sucesso` + `indeterminado` como
número confiável ainda sem julgamento (`AGUARDANDO_DECISAO_USUARIO`): por isso o worker nunca
emite essa combinação (um teste varre orçamentos e totais em torno da fronteira).

## A conferência contra o baseline

| Conferido | Divergência |
| --- | --- |
| `totais.baseline` igual ao total do período dos baselines congelados do worker | `erro_codigo`, motivo `baseline_divergente` |
| `diferenca_abs` igual a `simulado − baseline` | idem |
| `diferenca_pct` igual à fração da T-035 sobre esses centavos (0.0 com baseline zero) | idem |
| competência sem baseline no worker | idem |
| cada linha do detalhamento contra a linha do baseline do worker (T-262) | idem |
| a coerência entre o detalhamento, os totais e as quebras (T-262) | `erro_codigo`, motivo `resultado_incoerente` |

As contas são as da T-035 (`resultado.montar_resultado`) sobre os mesmos centavos, então a
igualdade é exata: uma divergência é adulteração ou descompasso, nunca arredondamento. Nenhum
número é recalculado para **substituir** o do container: o worker confere e acrescenta
`totais.orcamento`, quando há orçamento. `Julgamento.resultado` é o do container mais esse
campo, e valida inteiro contra `resultado-simulacao.schema.json`; é o que a T-067 grava.

## A conferência do detalhamento (T-262)

Com o detalhamento por competência e matrícula da T-259, o worker confere o resultado inteiro,
e não só o total. Ele não recalcula a regra: soma o que o container devolveu e compara com o que
o próprio container declarou e com o baseline que o worker mantém. As verificações rodam em todo
sucesso classificado, nesta ordem, e param na primeira que falha:

| Verificação | O que confere | Motivo |
| --- | --- | --- |
| `baseline` | o detalhamento traz exatamente as competências e matrículas do baseline do worker, e em cada linha a loja, a marca, o cargo e a comissão do baseline são os dele | `baseline_divergente` |
| `soma_do_detalhamento` | a soma de `comissao_simulada` é `totais.simulado` | `resultado_incoerente` |
| `diferencas` | em cada linha, `diferenca` é a comissão simulada menos a do baseline | `resultado_incoerente` |
| `contribuicoes` | em cada linha, as contribuições somam a `diferenca` | `resultado_incoerente` |
| `quebras` | `elemento` é a soma das contribuições; `loja`, `marca`, `cargo` e `competencia`, das diferenças; `matricula`, `loja_absoluto` e `competencia_absoluto`, das comissões simuladas | `resultado_incoerente` |

- **`baseline_divergente`** é o que a conferência do total já usava: o baseline que saiu do
  container, no total ou numa linha, não é o do worker. Numa execução na meta, o do worker é o
  reapurado sobre as vendas escaladas, também linha a linha.
- **`resultado_incoerente`** é a causa que a T-256 acrescentou ao contrato do diagnóstico: o
  baseline confere, mas o resultado não fecha consigo mesmo.
- **A igualdade é exata, em centavos.** As parcelas já chegam arredondadas por linha (T-035):
  uma divergência é adulteração ou defeito, nunca arredondamento.
- **As chaves das quebras são as que o harness cria.** As quebras por loja, marca, cargo e
  matrícula têm uma chave para cada código das linhas, mesmo com soma zero, e as por competência
  têm uma para cada competência do período. Por elemento, o harness guarda o elemento cujas
  parcelas somam zero (T-241), e o detalhamento omite a parcela zero da linha: um elemento que só
  aparece na decomposição é aceito se valer zero.
- **As três quebras absolutas são exigidas num sucesso.** O contrato as deixa opcionais pelos
  resultados gravados antes da T-259; o harness sempre as produz.
- **A conferência vem antes da cobertura**, que lê a quebra por elemento: com o detalhamento
  incoerente, a cobertura nem é conferida.

Um resultado recusado é gravado como `erro_codigo`, com `linhas` nula, sem veredito, e com a causa
no diagnóstico (`{"causa": "baseline_divergente"}` ou `{"causa": "resultado_incoerente"}`). Os
baselines não mudam, e `app/execucao/baseline.py` não entra no hash do motor:
`python -m scripts.build_baselines --check` continua passando.

## Observabilidade

O log `execução julgada` leva classe, motivo, veredito e `desfecho`, e o `execução preparada`
leva `com_orcamento` (se haverá veredito, nunca o valor). Num resultado que passou pela
conferência, o `execução julgada` leva também `conferencia` (`coerente`, `baseline_divergente` ou
`resultado_incoerente`) e, na recusa, `verificacao`, a verificação que falhou, de conjunto
fechado: `baseline`, `soma_do_detalhamento`, `diferencas`, `contribuicoes` ou `quebras`. Nenhuma
matrícula nem valor do detalhamento vai ao log. `job_resultado_conferencia_total{resultado}`
conta cada resultado conferido pelo que a conferência decidiu; a reentrega que só republica não
confere de novo e não conta, e o desfecho que não é sucesso não chega à conferência. `worker_execucoes_julgadas_total`
conta cada execução julgada pelo `desfecho`, de conjunto fechado: `viavel`, `inviavel`,
`sem_orcamento`, `assercao_violada`, `erro_codigo` e `erro_infra`. Conta execuções, não jobs: a
reentrega que republica um resultado já gravado não executa nem julga e não conta, e cada
tentativa de um `erro_infra` conta uma vez.

### Por que a conferência existe, com um ataque real

O harness guarda o baseline em registros Python que a regra nunca recebe (T-033). Mas a regra
roda **no mesmo processo**: `gc.get_objects()` entrega esses registros. Uma regra que os infla em
10% e devolve uma decomposição coerente produz, com a imagem real, um `sucesso` com todas as
invariantes reconciliando e uma economia inventada de R$ 50.838,31 sobre novembro. Para o
harness e para a classificação da T-065 é um resultado legítimo; só a comparação com o baseline
que o worker leu por conta própria o denuncia
(`test_regra_que_infla_o_baseline_do_harness_e_denunciada_pelo_worker`, com a imagem real).

### O que ela não pega

- **A redistribuição entre matrículas passou a ser detectada.** Só com o total, uma regra que
  movesse baseline entre matrículas **preservando o total** passava. Com as linhas da T-259, a
  conferência da T-262 a recusa como `baseline_divergente`
  (`test_regra_que_redistribui_o_baseline_preservando_o_total_e_denunciada_linha_a_linha`, com a
  imagem real).
- **Nada fora do container recalcula o total simulado.** Uma regra que leia o baseline da
  imagem e forje um envelope com o baseline certo e um simulado à escolha passa: o sandbox
  garante que o código não é perigoso, não que está correto (ARCHITECTURE.md §1.4). A camada
  que responde pela correção do cálculo é a regra de referência (T-036) e a cobertura do
  escopo (T-056).

## O container não recebe o orçamento

Três provas, cada uma com o controle que mostra a sonda funcionando:

- **Unitária:** o payload serializado, as opções do container e o `repr` do payload não contêm
  o orçamento em nenhuma forma; `ExecucaoPreparada` o retém fora do payload.
- **Com a imagem real:** uma regra-sonda procura o orçamento, em quatro grafias (`487123.45`,
  `48712345`, `487123,45`, `487123.4`), como `float`, `Decimal`, texto e bytes, em todo o
  processo: ambiente, `sys.argv`, `/proc/self/cmdline` e o conteúdo de todo objeto vivo, o que o
  harness leu do stdin inclusive. Não acha nada. O controle, com o valor plantado de propósito
  num objeto vivo, acha.
- **A imagem não tem o código que julga:** `app/execucao/` não é copiado pelo Dockerfile do
  sandbox (teste estático), e `import app.execucao.veredito` falha dentro da imagem
  (teste com Docker).

## Os baselines do worker

Os arquivos são os mesmos que abastecem a imagem do sandbox, e o worker os lê por conta
própria (`sandbox/data/domrock/baselines`). Não pode usar `app/sandbox/carga.py`, que importa
pandas. Na carga, para cada competência do manifesto: o sha256 do arquivo, a contagem de
matrículas e o total precisam bater com o manifesto, cada linha tem exatamente as colunas de
`apuracao_base` (contrato T-034: sem `nivel`, `cargo` nem linhas agregadas; os três níveis vivem
em `baselines/auditoria/` e não são lidos aqui), cada comissão tem de ser exata em centavos e
nenhuma matrícula pode repetir. Um baseline ausente ou adulterado derruba o worker na subida,
e não o primeiro job. São **cinco** competências (2025-08 a 2025-12); o texto da tarefa fala em
seis.

**Imagem do sandbox e worker precisam do mesmo baseline.** Os dois saem do mesmo checkout no
deploy (`cd-worker.yml` constrói os dois). Um descompasso vira `baseline_divergente` em todo
job, o que a T-065 leva a `erro_codigo` e o codegen regenera até esgotar as tentativas.

## Pendências

- **T-067** (feita, `docs/t067-gravacao-e-publicacao.md`): grava `resultados_simulacao` a partir do
  `Julgamento` e publica `simulacao-concluida`, mapeando o `indeterminado` interno para veredito
  nulo/ausente.
- **DEC-093** registra que a igualdade é viável. Se a PO preferir a leitura conservadora,
  reverter é trocar `<=` por `<` em `decidir_veredito`, e os testes de fronteira acusam o que
  atualizar junto.

## Verificação

Na pasta `worker/`:

```bash
poetry run pytest tests/app/execucao/test_veredito.py tests/app/execucao/test_baseline.py
poetry run pytest tests/app/execucao/test_conferencia.py
poetry run pytest tests/app/execucao/test_coleta_integration.py   # imagem real do sandbox
poetry run pytest tests/app/execucao/test_conferencia_integration.py   # imagem real do sandbox
sh verify.sh                                                      # com o compose de pé para postgres e rabbitmq
docker build -f worker/Dockerfile .                               # da raiz do monorepo
```
