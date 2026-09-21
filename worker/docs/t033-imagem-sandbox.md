# T-033 — Imagem do sandbox

A imagem `synapse-sandbox` é o container efêmero onde o código gerado pela IA roda. Ela não
tem rede, e tudo que o código precisa ler está dentro dela antes de subir; só o código a
executar chega de fora, pelo stdin. O worker (T-064) sobe um container por job, aplica as
flags de isolamento e descarta o container ao final.

```bash
# da raiz do monorepo, como as demais imagens
docker build -f worker/sandbox/Dockerfile -t synapse-sandbox:local .

docker run --rm -i --network none --read-only synapse-sandbox:local < payload.json
```

O build a frio leva cerca de 50 s e a imagem tem 256 MB, dos quais 142 MB são o venv com
pandas e numpy.

## Como cada coisa entra

Três insumos, três caminhos distintos. Nenhum volume é montado e nenhuma rede é usada.

| Insumo | Quando entra | Por onde |
| --- | --- | --- |
| Bases e baselines | **build** da imagem | `COPY` por lista branca, para `/app/sandbox/data/domrock/` |
| Motor, harness e ponto de entrada | **build** da imagem | `COPY` por lista branca, para `/app/app/sandbox/` |
| Código gerado e competências | **execução**, a cada job | JSON de uma linha no **stdin**; o resultado volta no **stdout** |

O layout dentro da imagem espelha o do repositório (`app/sandbox/` e `sandbox/data/`), porque
`resultado.py` importa os irmãos por `app.sandbox.*` e `carga.py` acha os dados relativo ao
próprio arquivo. O mesmo cálculo serve ao repositório e à imagem.

## O que entra e o que fica de fora

| Fora da imagem | Motivo |
| --- | --- |
| `app/sandbox/daemon.py` | importa `docker`, `app.config` e `app.core.logger`: daria ao container que roda código não confiável o cliente do daemon |
| `app/sandbox/regras_competencia.py` | só serve para recomputar baselines (T-032); aqui o baseline é dado congelado |
| `regras_competencia.jsonl` | insumo do recálculo, que o harness não faz |
| `normalization_report.json` | 1,85 MB de relatório da T-026; não é base |
| `contracts/` | a imagem não valida schema (sem `jsonschema`, pela lista da T-034) |
| `pip`, do venv **e** do Python do sistema | a lista de bibliotecas é a da T-034 e nada além |

A cópia é por lista branca, um arquivo por linha, nunca `COPY worker/app`. Módulo novo que
ninguém listou não entra na imagem. Três testes fecham isso: um lê o Dockerfile, outro
inspeciona a imagem construída, e um terceiro prova que o processo do worker não alcança o
`exec` de código gerado.

Entram as três bases, a tabela de eventos de RH **inteira** (2025-07 a 2025-12, porque um
evento de julho ainda afeta um mês posterior), o `schema.json` e os baselines congelados das
cinco competências publicadas, com o `manifesto.json`.

**Cinco competências, não seis.** O texto original da tarefa fala em seis. Julho foi excluído
pela T-026 (`EXCLUDE_2025_07`, confirmado em 15/09/2026) e `schema.json` declara
`published_competencias` com cinco: Ago–Dez/2025.

## O payload e o envelope

O worker escreve um JSON de uma linha no stdin e lê o envelope no stdout.

```json
{"job_id": "3f2b1c40-...", "codigo_gerado_id": "5d4c3b2a-...", "linguagem": "python",
 "competencias": ["2025-11"], "fonte": "def aplicar_regra(bases, apuracao_base, competencias): ..."}
```

Os campos são exatamente os de `PayloadContainer` (`app/execucao/preparo.py`), e um teste
confere que as duas listas não divergem. **O orçamento nunca entra**: campo desconhecido é
recusado, não ignorado, e a mensagem de erro não repete o valor.

A fonte viaja como valor de string do JSON e volta byte a byte igual; o payload é lido em
binário e decodificado como UTF-8 explícito, então o locale do container é irrelevante. O
código gerado **não é escrito em disco**: `harness.carregar_regra` compila a string e a executa
num módulo em memória, e semeia o `linecache` para o traceback sair com a linha ofensora.

O envelope (`app/sandbox/envelope.py`) é uma linha, determinística, no vocabulário de
`resultados_simulacao.status`, sem `erro_infra`: o container nunca se declara quebrado.

| Código de saída | Envelope | `status` | Quando |
| --- | --- | --- | --- |
| `0` | sim | `sucesso` | resultado montado |
| `2` | sim | `assercao_violada` | comissão negativa ou não finita; o número não vale |
| `3` | sim | `erro_codigo` | a regra quebrou, devolveu fora do contrato ou a decomposição não reconcilia |
| `1` | **não** | — | falha do próprio harness ou do dado embutido; o motivo vai para o stderr |

O `1` é o código que o Python devolve para exceção não tratada, e por isso é o do harness:
uma falha inesperada nunca é atribuída à regra por engano. Só `ResultadoInvalidoError` e a
falha ao rodar a própria regra viram `erro_codigo`; qualquer outra exceção na agregação sobe
como bug do harness.

`resultado` só existe em `sucesso` e, com `totais.orcamento` acrescentado pelo worker (T-066),
valida contra `resultado-simulacao.schema.json`. `erro` carrega tipo, mensagem (1000
caracteres) e os quadros do traceback que são da própria regra (8000 caracteres). **Esse
conteúdo é dado não confiável**: quem o consome o trata como texto, nunca como instrução, e
não o registra em log.

## O que impede um número errado com aparência de certo

O pior modo de falha deste desenho é a regra e o harness rodarem no mesmo processo (contrato
T-034: o modelo não dá isolamento, a contenção vem das flags do container). Cada defesa abaixo
tem um teste que falha quando ela é removida.

- **A regra recebe cópias.** `apuracao_base.copy(deep=True)`, bases copiadas e uma lista nova de
  competências. Uma regra que altere o que recebeu não altera o que o harness guarda.
- **A agregação usa um baseline que a regra nunca viu.** `Entrada.registros_base` são registros
  Python construídos antes da chamada. Sem isso, uma regra que rebaixasse o baseline recebido
  e declarasse a diferença correspondente produziria economia inventada com tudo reconciliando:
  nenhuma exceção, nenhuma asserção violada.
- **O stdout é só do envelope.** O descritor 1 é duplicado para o envelope e depois apontado
  para o stderr. Redirecionar só `sys.stdout` não basta: `os.write(1, ...)`, um subprocesso ou
  uma biblioteca em C ainda vazariam para o JSON.
- **`sys.exit()` na regra não parece sucesso.** `SystemExit` não é `Exception`; sem tratamento
  próprio o processo sairia com `0` e sem envelope.
- **`compile(..., dont_inherit=True)`.** Sem isso a regra herdaria o
  `from __future__ import annotations` do harness. E o módulo fica em `sys.modules`, porque
  `@dataclass` consulta `sys.modules[cls.__module__]`.

## A carga, com tipos explícitos

`app/sandbox/carga.py` lê os JSONL e entrega DataFrames com dtype explícito, conforme a
"Convenção de tipos das colunas" do contrato: códigos `int64`, valores `float64`, texto e
objeto em `object`, e nulo continua `None`. Nunca `DataFrame(registros)` nem `read_json`:
inferir daria `float64` num período sem linhas, onde o contrato manda `int64`.

`rh`, `vendas` e `comissoes` são recortadas ao período do job; `eventos_rh` chega inteira. O
mapa de tipos é conferido por teste contra o `schema.json`, para não haver duas fontes de
verdade em silêncio.

**`apuracao_base` na forma do contrato.** O baseline em disco (T-032) já tem exatamente as
seis colunas declaradas pela T-034: `matricula`, `cod_loja`, `cod_marca`, `cod_cargo`,
`competencia` e `comissao`. A carga não filtra nível, não renomeia cargo e não reconstrói marca;
apenas valida competência, unicidade, dimensões contra o RH, contagem e total contra o
`manifesto.json`. Os antigos níveis `total`, `loja` e `matricula` continuam disponíveis em
`baselines/auditoria/`, mas não entram em `apuracao_base`.

## Asserções: só `sem_comissao_negativa`

As outras duas da T-031 não funcionam sobre saída gerada, e rodá-las seria pior que não rodar:

- `soma_loja_igual_soma_matricula` compara as linhas com um acumulador de lojas produzido
  durante o cálculo pelo motor da T-030. Derivá-lo das próprias linhas simuladas compara a soma
  com ela mesma: a checagem passa sempre e mente.
- `sem_comissao_sem_venda` exige as origens declaradas, que a representação da regra (fora do
  container) informaria. Sem elas, reprovaria uma regra legítima de bônus fixo.

O risco de "comissão do nada" continua coberto: a agregação (T-035) recusa toda diferença sem
elemento que a assuma. A invariante mora em `harness.py`, e não em `assercoes.py`, porque o
manifesto da T-032 registra o sha256 desse arquivo (`motor_sha256`): editá-lo invalidaria o
congelamento dos baselines.

## Reprodutibilidade

"Construir duas vezes a partir do mesmo commit produz o mesmo conteúdo funcional."

| Garante | Como |
| --- | --- |
| Mesmas bibliotecas | pins exatos de pandas e do fecho transitivo, `--only-binary` e teste de inventário |
| Ambiente de teste = imagem | teste compara `sandbox/requirements.txt` com o `poetry.lock` |
| Sem fetch dinâmico | nenhum `apt-get`, nenhum download em runtime |
| Mesmos dados | arquivos do próprio commit; sha256 dos baselines conferido contra o manifesto dentro do container |
| Mesma saída | `PYTHONHASHSEED=0`, `OMP_NUM_THREADS=1` e teste de duas execuções byte a byte |

O que **não** é bit a bit: timestamps de camada e a data de criação da imagem. A imagem base
fica na tag `python:3.12-slim`, como os demais Dockerfiles; pinar por digest é decisão para
uma tarefa de supply chain.

Uma consequência que vale saber: somas de ponto flutuante dependem da ordem. Com a regra de
exemplo do contrato, a diferença de novembro sai `-14344.54` com o `groupby` do pandas e
`-14344.53` numa soma sequencial em Python. É a aritmética da regra, não do harness, e por isso
os testes ancoram no que é exato (o baseline, `508382.32`) e usam tolerância declarada no resto.
Trocar a versão do pandas pode mudar centavos, e é para isso que ela é pinada.

## Ciclo de vida do container

Medido contra a imagem real, conduzida pelo SDK do Docker, que é o que o worker usa
(`test_ciclo_de_vida_container.py`). O `ContainerDoSandbox` desse arquivo é um cliente de
referência **só de teste**: não é código de produção, e a T-064 não é obrigada a copiá-lo.

| Situação | Saída | Envelope | Observação |
| --- | --- | --- | --- |
| execução normal | `0`, `2` ou `3` | sim | o container termina sozinho e é removido |
| stdin sem EOF | — | — | o container **espera para sempre**: o payload termina no EOF, e a T-064 precisa fechá-lo |
| `docker kill` (timeout de parede) | `137` | não | morre em 0,2 s |
| `docker stop` | `143` | não | morre em 0,1 s, graças ao handler de SIGTERM |
| estouro de memória | `137`, com `OOMKilled` | não | é o `OOMKilled` que distingue de um kill por timeout |
| `os._exit(0)` na regra | `0` | **não** | verificado à mão, sem teste; parece sucesso para quem só olha o código |

**O executor é o PID 1 do container**, e o kernel não entrega a um PID 1 um sinal sem handler.
Sem o handler de SIGTERM (`executor._encerrar_ao_receber_sigterm`), `docker stop` ignorava o
sinal e o container só morria pelo SIGKILL ao fim do prazo: 3,2 s com `-t 3`, 10 s com o prazo
padrão. O handler usa `os._exit`, e não `SystemExit`, porque a regra pode capturar `SystemExit`.

A receita do SDK que a T-064 vai precisar, na ordem que funciona:

```python
c = cliente.containers.create(imagem, stdin_open=True, network_mode="none", read_only=True)
soquete = c.attach_socket(params={"stdin": 1, "stream": 1})   # ANTES de iniciar
c.start()
soquete._sock.sendall(payload)
soquete._sock.shutdown(socket.SHUT_WR)                        # EOF, sem fechar a leitura
c.wait(timeout=...)                                           # levanta ReadTimeout se estourar
c.logs(stdout=True, stderr=False)                             # só o envelope
c.remove(force=True)                                          # em um finally, aconteça o que acontecer
```

O timeout de `wait` **não mata** o container; quem mata é o `kill()`. Envelope presente com
`0`, `2` ou `3`; `0`, `137` ou `143` sem envelope nunca é veredito do código gerado.

## Limite desta entrega e pendências para a T-064

A imagem existe, mas **nada em produção a sobe nem captura o resultado**. Hoje
`app/mensageria/consumidor.py` termina em `preparar_execucao` e faz `ack`: ninguém sobe o
container, escreve o payload, lê o envelope, persiste em `resultados_simulacao` ou publica
`simulacao-concluida`. Um `executar-codigo` recebido hoje é consumido e o resultado se perde.
Os testes capturam o stdout com `subprocess` e com o SDK, como um substituto do worker. Fica
para a T-064 (e T-065/T-066):

- o nome da imagem (`synapse-sandbox`, padrão do `deploy/docker-compose.yml`) e onde configurá-lo
  (`SANDBOX_IMAGE` em `app/config.py`), e quem a constrói no deploy;
- as flags: `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, limites
  de CPU, memória e PIDs, timeout de parede com kill e `--rm`;
- escrever o payload no stdin **e fechar o stdin**, senão o `read()` do executor bloqueia; impor
  um teto de leitura do stdout;
- o mapa código de saída → status: `0`, `2` e `3` com envelope; **sem envelope**, `1` ⇒ falha do
  harness, `143` ⇒ encerrado por `stop`, `137` ⇒ timeout (nosso `kill`) ou estouro de memória
  (`OOMKilled`), e `0` ⇒ erro, porque um `os._exit(0)` da regra não escreve nada;
- `tempfile` falha sob `--read-only` (`FileNotFoundError: No usable temporary directory`).
  Nada na carga usa scratch, então não é preciso `--tmpfs` hoje; se entrar biblioteca que
  precise, é `--tmpfs /tmp:rw,noexec,nosuid,size=64m` na execução, e não afrouxar a imagem;
- o `apuracao_base` que sai no resultado é reconferido fora do container (T-066), **em
  centavos**: aqui as parcelas são quantizadas por linha.

`exec` de código gerado mora em `worker/app/sandbox/harness.py`, e o `worker/Dockerfile` copia
`worker/app` inteiro; nada importa esse módulo no processo do worker, e
`test_isolamento_harness.py` prova isso por percurso estático de imports e por `sys.modules` em
runtime. `envelope.py` só depende de stdlib e da agregação, para a T-064 poder importá-lo.

## Verificação

Na pasta `worker/`:

```bash
poetry run pytest tests/app/sandbox/                 # unitários, sem Docker
poetry run pytest -m docker tests/app/sandbox/       # constrói a imagem e testa os critérios
sh verify.sh                                         # o gate do componente
```

`SANDBOX_IMAGE_TESTE=<tag>` reusa uma imagem já construída em vez de construir.

Cada critério de aceitação tem teste contra a imagem real: execução do exemplo do contrato
sobre novembro com `--network none --read-only`, usuário não-root, inventário exato de
bibliotecas, presença das bases, dos eventos e dos baselines, e ausência de orçamento, por uma
varredura que separa **menção** de **valor** (chave de dado ou símbolo do programa, nunca
comentário ou docstring) e tem controle negativo que prova que ela reconhece o que deveria.
