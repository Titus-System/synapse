# T-065: coleta do resultado e classificação do desfecho

`executar_no_sandbox` (T-064) devolve fatos. Esta entrega os lê e decide **de que tipo** foi o
desfecho, no vocabulário de `resultados_simulacao.status` e do evento `simulacao-concluida`:
`sucesso`, `assercao_violada`, `erro_codigo` e `erro_infra`. A classe decide o tratamento a
jusante, e ela é calculada **uma vez, aqui**: a api (T-045) a mapeia para o estado do job e o
codegen (T-059) roteia o grafo por ela, sem reimplementá-la.

O worker não interpreta nem recalcula número nenhum. Ele coleta, confere a forma e classifica; o
resultado de sucesso segue **como veio do container**.

## Onde está

| Arquivo | O quê |
| --- | --- |
| `app/execucao/coleta.py` | `classificar`, `classificar_falha_de_infra`, `DesfechoClassificado` |
| `app/execucao/schema.py` | validação do resultado contra `contracts/domain/resultado-simulacao.schema.json` |
| `app/mensageria/consumidor.py` | executa, classifica, registra a classe no log e dá `ack` |
| `app/main.py` | `carregar_contratos()` na subida: sem `contracts/`, o worker não sobe |

## O que é capturado

Em toda execução, `SaidaBruta` guarda o código de saída, `OOMKilled`, se o prazo estourou, o
stdout, o stderr (cada um com teto de leitura, e o corte sinalizado) e a duração;
`DesfechoClassificado.saida` a carrega adiante. Não há "artefato de saída" em arquivo: com o
sistema de arquivos somente leitura (T-064), o resultado **é** o envelope do stdout.

## A ordem da classificação

A primeira regra que casa vence. Só a `erro_infra` vem de fora desta tabela: é a captura de
`SandboxInfraError` no consumidor (criar, iniciar, inspecionar ou ler o container falhou).

| # | Condição | Classe | Motivo |
| --- | --- | --- | --- |
| 1 | `estourou_timeout` | `erro_codigo` | `timeout` |
| 2 | `oom_killed` | `erro_codigo` | `memoria` |
| 3 | stdout cortado no teto | `erro_codigo` | `saida_truncada` |
| 4 | stdout vazio (saída 1, 0 sem envelope, 137, 143) | `erro_codigo` | `sem_envelope` |
| 5 | não é uma linha de JSON válido (UTF-8, sem `NaN`), ou é mas não tem a forma nem a coerência do envelope | `erro_codigo` | `envelope_invalido` |
| 6 | `job_id`, `codigo_gerado_id` ou `competencias` diferem do payload | `erro_codigo` | `envelope_de_outra_execucao` |
| 7 | código de saída diferente do que o `status` do envelope implica | `erro_codigo` | `codigo_de_saida_divergente` |
| 8 | `status == "assercao_violada"` | `assercao_violada` | `assercao` |
| 9 | `status == "erro_codigo"` | `erro_codigo` | `excecao` |
| 10 | `status == "sucesso"`, mas o resultado não valida no schema | `erro_codigo` | `resultado_fora_do_schema` |
| 11 | `status == "sucesso"` e o resultado valida | `sucesso` | `ok` |

O **motivo** é para log, métricas e para a gravação (T-067). Nunca carrega conteúdo do
container, e no caso 10 `problemas` lista onde o schema falhou (`$.decomposicao: required`),
sem valores.

### A forma e a coerência (regra 5)

O harness sempre produz um envelope de forma fixa, e um que a contradiz não foi escrito por
ele. Reprovam: chave a mais ou a menos; `versao` diferente de 1; tipos errados; `assercoes`
fora do schema `resultado-assercoes`; e as incoerências:

- `sucesso` sem `resultado`, com `erro`, com alguma asserção `violada`, ou cuja lista de
  asserções difere da de `resultado.assercoes`;
- `assercao_violada` com `resultado`, com `erro`, ou **sem** nenhuma asserção violada;
- `erro_codigo` sem `erro`, ou com `erro` fora de `tipo`, `mensagem` e `traceback` em texto.

## As decisões

1. **Sem envelope válido, a culpa é do código.** O contrato da T-033 chama a saída 1 sem
   envelope de "falha do próprio harness", e a documentação daquele desenho a queria fora do
   `erro_codigo`. Mas a regra roda no **mesmo processo** do harness e forja isso com
   `os._exit(1)`: tratá-la como `erro_infra` daria a um código hostil um jeito de escapar da
   regeneração e de ganhar repetições. O harness é determinístico e tem testes próprios, então
   um bug dele apareceria antes; errar para `erro_codigo` custa uma regeneração, errar para
   `erro_infra` abre uma brecha. O único `erro_infra` é a falha ao subir, iniciar ou ler o
   container.
2. **Timeout e OOM são `erro_codigo`, sempre**, inclusive quando um envelope de sucesso completo
   chegou (uma thread não-daemon viva depois de o envelope escrito faz o processo morrer só pelo
   nosso SIGKILL). O contrato não tem classe própria para eles, e um resultado de um processo
   que não terminou limpo não vale. Repetir o mesmo código daria o mesmo resultado.
3. **A validação usa o schema da T-034, em runtime, fora do container.** A imagem do sandbox só
   admite pandas e a biblioteca padrão, e quem escreveu o resultado é código não confiável, que
   não pode ser também quem o valida. O schema exige `totais.orcamento`, que o container não
   recebe, então a validação vê uma **cópia** com o orçamento do comando acrescentado; o objeto
   que segue adiante é o do container, sem o campo. `jsonschema` passou a dependência de
   runtime; os schemas vêm de `contracts/`, que o build da imagem já copia (ADR-002).
4. **Um `totais.orcamento` na saída do container é reprovado** (`resultado_fora_do_schema`,
   problema `$.totais.orcamento: fornecido_pelo_container`). O harness não o produz: alguém o
   fabricou, e ele não pode chegar ao veredito parecendo dado do container.

## A relação entre a classe e o `retry_count`

Há dois contadores diferentes, e a classe decide qual deles anda:

- `synapse_retry_count` é o **header AMQP** do worker (DEC-091): republicações do mesmo
  comando, três tentativas no total. É o único retry automático do worker.
- `jobs.tentativas` é da **api**: as gerações de código do job. Só a api o escreve.

| Classe | Retry automático do worker | O que acontece com o job |
| --- | --- | --- |
| `erro_infra` | **sim**: o mesmo comando, até 3 tentativas (`synapse_retry_count` 0, 1, 2), e depois a DLQ | nenhuma geração nova; `jobs.tentativas` não anda |
| `erro_codigo` | não: o mesmo código daria o mesmo resultado | o codegen gera código novo (T-059) e a api conta uma tentativa |
| `assercao_violada` | não | idem, mas distinta de `erro_codigo` para que o codegen diga ao modelo que o número saiu inválido, e não que o código quebrou |
| `sucesso` | não | segue para o veredito (T-066) |

`assercao_violada` também **não** é inviabilidade: inviabilidade é uma regra coerente que não
cabe no orçamento, com veredito `inviavel`; asserção violada é número que não vale e nunca
recebe veredito.

## O que a classificação não garante

Tudo que vem do container é dado não confiável, o envelope inteiro inclusive. A regra divide o
processo com o harness e, achando o descritor onde ele guarda o canal do envelope, escreve nele
o que quiser (um teste com a imagem real faz exatamente isso). A classificação confere forma,
identidade e coerência, mas **não autentica**: um envelope forjado que seja bem formado e
tenha resultado válido no schema passa. O que fecha essa porta é a reconferência do
`apuracao_base` contra o baseline congelado, fora do container, que é da T-066.

Stdout, stderr e a mensagem de erro da regra são texto para o usuário, nunca instrução para um
agente, e **não vão a log**: o log carrega só a classe, o motivo, o código de saída e os
caminhos que falharam no schema. O `repr` de `DesfechoClassificado` omite `resultado`, `erro`,
`assercoes` e `saida` pelo mesmo motivo.

## Pendências

- **T-066**: acrescentar `totais.orcamento` ao resultado, reconferir o `apuracao_base` em
  centavos e calcular o veredito, a partir do `DesfechoClassificado`.
- **T-067**: gravar `resultados_simulacao` e publicar `simulacao-concluida`. Hoje a classe só vai
  ao log e o comando recebe `ack`, então o resultado ainda não sai do worker.
- **Comando que esgota as três tentativas de `erro_infra`** vai para a DLQ, e a DLQ não publica
  resultado (DEC-091): o job fica sem desfecho. A T-067 deve decidir se publica `erro_infra`
  nesse momento; o evento e a tabela já têm essa classe.

## Verificação

Na pasta `worker/`:

```bash
poetry run pytest tests/app/execucao/test_coleta.py tests/app/execucao/test_schema.py
poetry run pytest tests/app/execucao/test_coleta_integration.py      # imagem real do sandbox
poetry run pytest tests/app/mensageria                                # consumidor; os de integração pedem o compose
sh verify.sh
```

`test_coleta.py` prova uma linha da tabela por teste, com saídas montadas à mão (código hostil
escreve qualquer byte no stdout). `test_coleta_integration.py` produz cada classe com um
container de verdade, inclusive a regra que sai com `os._exit(1)` e a que forja um envelope de
sucesso. `test_consumidor_execucao_integration.py` percorre o fluxo com RabbitMQ, Postgres e
container reais, num vhost isolado: no vhost padrão, um worker do compose de pé é outro
consumidor da mesma fila e o RabbitMQ reparte as mensagens entre os dois.
