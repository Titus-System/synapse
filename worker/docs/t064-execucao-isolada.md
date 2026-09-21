# T-064 — Execução isolada do código gerado

`app/execucao/container.py` sobe um container efêmero por execução a partir da imagem da
T-033, entrega o código pelo stdin, espera o prazo, mata se precisar e devolve a saída
bruta. A T-033 define **o que existe dentro** do container; esta tarefa define **como ele
é executado**.

```python
saida = executar_no_sandbox(payload)          # PayloadContainer, de app/execucao/preparo.py
saida.codigo_saida, saida.oom_killed, saida.estourou_timeout, saida.stdout, saida.stderr
```

O módulo devolve **fatos, não veredito**. Classificar a execução em `sucesso`,
`erro_codigo`, `assercao_violada`, timeout ou `erro_infra` é da T-065, pelo mapa de
códigos de saída registrado em [t033-imagem-sandbox.md](t033-imagem-sandbox.md).

## As flags, e o que cada uma impede

O código gerado é tratado como **potencialmente malicioso**, sempre: a hipótese não é "o
modelo errou", é "este código pode estar tentando escapar". Cada linha abaixo tem um teste
que executa código tentando violá-la.

| Flag | Impede |
| --- | --- |
| `network_mode="none"`, `network_disabled=True` | exfiltrar dado, baixar código, alcançar o Postgres ou o RabbitMQ |
| `read_only=True` | persistir qualquer coisa, adulterar o motor, o baseline ou a si mesmo |
| `ipc_mode="none"` | escrever em `/dev/shm`, que o Docker monta `1777` **mesmo com `--read-only`** |
| `cap_drop=["ALL"]` | montar, mudar dono, abrir socket raw, carregar módulo do kernel |
| `security_opt=["no-new-privileges:true"]` | escalar privilégio por binário setuid |
| `mem_limit` e `memswap_limit` iguais | consumir a memória do host; sem swap, quem mata é o cgroup |
| `nano_cpus` | tomar a CPU do host |
| `pids_limit` | fork/thread bomb |
| `environment={}`, nenhum volume | receber credencial, orçamento ou o socket do Docker |
| `log_config` json-file com `max-size` | encher o disco do host pelo stdout, e garante o driver que `logs()` sabe ler |

O usuário não-root **não** está nessa lista de propósito: ele vem da imagem (T-033). O
teste confere que continua valendo — `uid` 1000, `CapEff` zerado, `NoNewPrivs: 1`,
`Seccomp: 2` e `os.setuid(0)` com `EPERM`.

**Nada disso é configurável.** As flags e os limites são constantes do módulo, e não
variáveis de ambiente: um ambiente que pudesse afrouxá-los deixaria de conter o raio de
dano justamente onde ele importa. Só o nome da imagem vem do ambiente (`SANDBOX_IMAGE`).
O parâmetro `limites` existe para os testes encurtarem prazo e memória — o caminho
exercitado continua sendo o de produção, e um teste fixa os valores de produção.

## Não há diretório de saída

O texto da tarefa e a arquitetura (§3.4) falam em "somente leitura **exceto o diretório
temporário de saída**". Esse diretório não existe: a T-033 fez do **stdout** o canal de
saída, e o container não escreve arquivo nenhum. Então a restrição vale na forma mais
forte — toda escrita falha, inclusive em `/dev/shm`.

Medido de dentro do container: `/`, `/app`, `/app/app/sandbox/harness.py`, os JSONL das
bases, o `site-packages`, `/tmp`, `/var/tmp`, `/etc/hosts` e `$HOME` devolvem `EROFS`, e
`/dev/shm` sequer existe. Há ainda uma segunda camada, que não depende do worker: os
arquivos entram na imagem com modo `0444` e dono `root`, então continuam irregraváveis
mesmo num container sem `--read-only` (é o que o controle do teste mostra, com `EACCES`).

Se um dia entrar biblioteca que precise de rascunho, a saída é
`--tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m` na execução — nunca afrouxar a imagem.

## Os números, e de onde vieram

Medidos contra a imagem real, com o exemplo do contrato sobre as cinco competências:

| Limite | Valor | Por quê |
| --- | --- | --- |
| memória | 256 MiB | pico medido de 90 MiB (`memory.peak` do cgroup); abaixo de 96 MiB o container morre por memória. 2,8x o pico, com folga para a regra trabalhar sobre um dataset de 4,5 MB |
| prazo | 60 s | a execução leva 1,2 s; 50x de folga |
| CPU | 1,0 | uma execução por vez (`prefetch` 1); mais que isso seria tomar o host |
| PIDs | 64 | a execução real usa poucas threads (`OMP_NUM_THREADS=1`); 64 barra a bomba e sobra para o pandas |
| teto de stdout | 1 MiB | o envelope tem ~2 KB; quem escreve é código não confiável |
| teto de stderr | 64 KiB | o stderr do harness é curto; o resto é despejo |

Apertar mais trocaria regra legítima por timeout ou OOM intermitente, que é o defeito mais
caro de depurar deste fluxo. Os tetos são de **leitura**: truncar não mata a execução, só
evita que um despejo de gigabytes derrube o worker por memória.

## A ordem que funciona

```python
container = cliente.containers.create(imagem, **opcoes)      # nome sbx-<job>-<uuid>, rotulado
soquete = container.attach_socket(params={"stdin": 1, "stream": 1})   # ANTES de iniciar
container.start()
soquete._sock.sendall(payload); soquete._sock.shutdown(SHUT_WR)       # EOF obrigatório
container.wait(timeout=restante)                                      # prazo de parede
container.kill()                                                      # se estourou: SIGKILL
container.logs(stdout=..., stream=True)                               # lido até o teto
container.remove(force=True)                                          # num finally, sempre
```

Quatro detalhes decidem se isso funciona:

- **anexar antes de iniciar**: anexar depois perde os bytes escritos enquanto o executor
  já lia o stdin;
- **fechar só a escrita**: o executor lê o stdin até o EOF; sem o `shutdown` o container
  espera para sempre. `_sock` é privado do SDK, mas é o único caminho para meio-fechar;
- **matar é SIGKILL**: o prazo não pede cooperação, e o teste usa uma regra que ignora
  SIGTERM e engole `BaseException`;
- **remover num `finally`**: sucesso, erro, timeout ou exceção nossa, o container some. O
  que sobreviver a uma queda do worker é achado pelos rótulos `synapse.sandbox` e
  `synapse.job_id` (T-068).

O prazo é medido pelo relógio monotônico, e não pelo tipo da exceção: as exceções do
cliente HTTP do SDK descendem de `OSError`, então o `except` não precisa do `requests`.

Tudo é síncrono. Quem chamar de dentro do loop assíncrono entra por `asyncio.to_thread`,
como `app/sandbox/daemon.py` já faz, para não travar o heartbeat do RabbitMQ.

## O que `SaidaBruta` afirma

| Campo | Significa |
| --- | --- |
| `codigo_saida` | o que o container devolveu. Só é veredito do código gerado quando os dois campos abaixo são falsos |
| `oom_killed` | o cgroup matou por memória — é o que distingue de um kill por prazo, já que ambos saem `137` |
| `estourou_timeout` | **nós** matamos ao fim do prazo |
| `stdout` | o envelope, quando existe (a T-065 o interpreta) |
| `stderr` | dado **não confiável** vindo do código gerado: texto, nunca instrução, e não vai para log |
| `*_truncado` | a saída passou do teto e foi cortada na leitura |

`SandboxInfraError` é falha nossa ou do daemon (criar, iniciar, inspecionar, ler),
**nunca** do código gerado: quem recebe classifica como `erro_infra`, que é repetível, em
vez de culpar a regra.

## O gate não passa verde sem ter rodado

Os testes marcados `docker` são os que provam o isolamento. Pulados em silêncio, o gate de
segurança do componente ficaria verde sem nunca ter rodado. Em CI (`CI=true`) isso passou
a ser falha, em dois pontos: `verify.sh` sai com erro quando o daemon não responde, e um
hook em `tests/conftest.py` transforma em falha o pulo de qualquer teste marcado `docker`.
`EXIGIR_DOCKER=1` reproduz o comportamento localmente; sem nenhum dos dois, a máquina do
desenvolvedor sem daemon continua podendo pular.

## Verificação

Na pasta `worker/`:

```bash
poetry run pytest tests/app/execucao                       # unitários e isolamento
SANDBOX_IMAGE_TESTE=synapse-sandbox:test \
  poetry run pytest -m docker tests/app/execucao           # reusa uma imagem já construída
sh verify.sh                                               # o gate do componente
EXIGIR_DOCKER=1 sh verify.sh                               # falha se o daemon não responder
```

Cada critério de aceitação tem um teste que executa código tentando violar a restrição, e
as asserções são específicas para a sonda não passar por engano: `ENETUNREACH` para fora
contra `ECONNREFUSED` no loopback (prova que o socket funciona e o que falta é rede), e um
controle que roda a mesma sonda de escrita sem `read_only` e exige que ela grave.

## Limite desta entrega

`app/mensageria/consumidor.py` chama `executar_no_sandbox` (numa thread, via
`asyncio.to_thread`), classifica o desfecho (T-065, `docs/t065-coleta-e-classificacao.md`) e faz
`ack`; `SandboxInfraError` entra em `repetir_erro_infra`, e o desfecho do código gerado
(asserção, erro, timeout, OOM) não é repetido. A classe vai ao log, mas o resultado ainda não sai
do worker: o veredito é da T-066, e a gravação e a publicação são da T-067. Até lá, um comando
executado com sucesso não deixa resultado para o codegen.

Pendências registradas:

- **quem constrói `synapse-sandbox` no deploy**: o serviço `sandbox` de
  `deploy/docker-compose.yml` (perfil `build`, só constrói) e o passo de build de
  `.github/workflows/cd-worker.yml`, que roda antes do build do worker. O worker recebe
  `SANDBOX_IMAGE: synapse-sandbox:${TAG:-local}`, a mesma tag do build. Fora do CD, quem sobe o
  compose constrói à mão (`docs/instalacao.md`, seção 3); sem a imagem, a primeira execução
  falha com `SandboxInfraError`;
- **envelope junto com timeout**: uma regra pode deixar uma thread não-daemon viva depois
  de o envelope ser escrito, e o processo só morre pelo nosso kill. `SaidaBruta` reporta os
  dois fatos; quem decide é a T-065;
- **watchdog de órfãos** (T-068): a remoção aqui é garantida por `finally`, mas uma queda
  do próprio worker entre o `create` e o `remove` deixa container para trás. Os rótulos
  existem para isso;
- **isolamento adicional** (runtime tipo gVisor, userns-remap), que a arquitetura deixa
  para validar com a disciplina de segurança: hoje o container roda com o runtime padrão,
  o seccomp padrão do Docker e sem capability nenhuma.
