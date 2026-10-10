# T-066: conferência contra o baseline e veredito de orçamento

Depois de o container devolver o resultado e a T-065 o classificar, o processo do `worker`,
fora do container, faz quatro coisas, nesta ordem:

1. **confere** o `totais.baseline` que saiu do container contra o baseline congelado (T-032)
   que o worker lê por conta própria, e que os totais fecham entre si;
2. com isso, **a diferença** absoluta e percentual do container passam a ser as do baseline do
   worker, e seguem como vieram, sem recomposição;
3. quando o comando trouxe `elementos_exigidos`, **confere a cobertura** dos elementos da regra
   (T-241, `docs/t241-conferencia-de-cobertura.md`);
4. **aplica o orçamento** e emite o veredito, quando o comando trouxe orçamento.

O orçamento é o único parâmetro que **julga** o resultado, e nunca entrou no container: código
gerado que o enxergasse poderia mirar nele.

Um job sem orçamento (T-281) recebe `executar-codigo` sem o campo. As conferências 1 a 3 são as
mesmas, e só a 4 não acontece: o `sucesso` sai sem veredito e sem `totais.orcamento`, porque não
há critério que o julgue. Um baseline adulterado continua `baseline_divergente`, e uma cobertura
incompleta continua `cobertura_incompleta`.

Numa execução na meta de venda (T-270), não há baseline congelado da meta: a conferência 1 é contra o baseline que o próprio worker reapurou sobre as vendas escaladas, antes de subir o container (`app/execucao/bases.py`). As conferências 2 a 4 são as mesmas, e o veredito compara o simulado na meta com o orçamento. Todo `sucesso`, com ou sem meta, leva `totais.vendas_historicas`, lido das bases do worker e nunca do container. Detalhes em `docs/t270-execucao-na-meta.md`.

## Onde está

| Arquivo | O quê |
| --- | --- |
| `app/execucao/baseline.py` | `carregar_baselines`: os cinco baselines congelados, conferidos contra o manifesto |
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

As contas são as da T-035 (`resultado.montar_resultado`) sobre os mesmos centavos, então a
igualdade é exata: uma divergência é adulteração ou descompasso, nunca arredondamento. Nenhum
número é recalculado para **substituir** o do container: o worker confere e acrescenta
`totais.orcamento`, quando há orçamento. `Julgamento.resultado` é o do container mais esse
campo, e valida inteiro contra `resultado-simulacao.schema.json`; é o que a T-067 grava.

## Observabilidade

O log `execução julgada` leva classe, motivo, veredito e `desfecho`, e o `execução preparada`
leva `com_orcamento` (se haverá veredito, nunca o valor). `worker_execucoes_julgadas_total`
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

- **A conferência é do total do período**, e não de linha: o container não devolve as linhas da
  `apuracao_base`, só os totais e a decomposição (contrato T-034, congelado). O total basta para
  o veredito. Uma regra que redistribua comissão entre matrículas **preservando o total** não é
  detectada aqui; a decomposição por loja, marca e cargo sairia errada, mas o veredito não.
  Fechar isso exigiria mudar o envelope, que é fronteira interna do worker, para trazer as
  linhas.
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
poetry run pytest tests/app/execucao/test_coleta_integration.py   # imagem real do sandbox
sh verify.sh                                                      # com o compose de pé para postgres e rabbitmq
docker build -f worker/Dockerfile .                               # da raiz do monorepo
```
