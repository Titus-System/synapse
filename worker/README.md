# Worker de Execucao

O `worker` e o componente responsavel por executar, de forma isolada, o codigo Python gerado pela IA durante uma simulacao de regras de comissionamento.

Ele recebe comandos pelo RabbitMQ, inicia um container Docker efemero para cada execucao, coleta o resultado, aplica o criterio de orcamento fora do sandbox, persiste o resultado no PostgreSQL e publica o evento de conclusao.

## Responsabilidades

- Consumir o comando `executar-codigo` no RabbitMQ.
- Buscar no PostgreSQL a referencia do codigo gerado.
- Executar o codigo somente dentro de um container Docker isolado.
- Disponibilizar no sandbox o dataset e os baselines da competencia.
- Capturar resultado, `stdout`, `stderr`, timeout e erros de infraestrutura.
- Preservar a decomposicao do resultado por regra, loja, marca e cargo.
- Aplicar o veredito de viabilidade comparando o total simulado ao orcamento.
- Inserir o resultado no PostgreSQL.
- Publicar `simulacao-concluida` em uma exchange fanout para a API e o `codegen`.
- Remover o container ao final, inclusive em caso de erro ou timeout.

O worker nao interpreta linguagem natural, nao gera codigo e nao decide se uma regra pode ser liberada para producao. Essas responsabilidades pertencem ao `codegen` e a API, respectivamente.

## Fluxo

```mermaid
flowchart LR
	C[codegen] -->|executar-codigo| R[RabbitMQ]
	R --> W[Worker]
	W --> P[(PostgreSQL)]
	W --> D[Container sandbox]
	D --> W
	W -->|simulacao-concluida| F[Exchange fanout]
	F --> A[API]
	F --> C
```

O dataset nao transita pela fila. As bases normalizadas e os baselines devem estar embutidos na imagem do sandbox antes da execucao. O container recebe apenas o codigo e os metadados necessarios para a simulacao.

## Isolamento do sandbox

O codigo gerado e tratado como nao confiavel. Cada execucao deve usar um container descartavel com, no minimo:

- rede desabilitada (`network none`);
- usuario sem privilegios e sem acesso ao Docker socket;
- sistema de arquivos somente leitura, com diretorio temporario de saida;
- limites de CPU e memoria;
- timeout com encerramento forcado;
- lista minima e explicita de bibliotecas Python permitidas;
- limpeza garantida mesmo quando a execucao falhar.

O sandbox produz somente dados de simulacao. O veredito de orcamento e calculado pelo processo confiavel do worker, fora do container que executa o codigo gerado.

## Estado atual

O repositorio contem o esqueleto operacional do servico, incluindo:

- aplicacao FastAPI para `/health`, `/ready` e `/metrics`;
- configuracao por variaveis de ambiente;
- logs estruturados e metricas Prometheus;
- imagem Docker multi-stage;
- verificacoes de lint, tipos e testes;
- conexao com o RabbitMQ e declaracao da fila `executar-codigo`, duravel e com `prefetch` 1;
- verificacao do acesso ao daemon do Docker na subida do processo;
- loop consumidor de `executar-codigo`: le o codigo pela referencia do comando no Postgres (usuario com `SELECT` apenas) e prepara o payload de execucao, retendo o orcamento fora dele.

A subida do container efemero e a persistencia/publicacao do resultado sao as proximas partes do fluxo de negocio a implementar.

O acesso ao daemon e verificado na subida: se o socket do Docker nao estiver acessivel, o processo falha imediatamente com mensagem explicita em vez de subir e quebrar so na primeira execucao. O pre-requisito de ambiente esta em [docs/instalacao.md](../docs/instalacao.md) secao 2.1.

## Requisitos

- Python 3.12+
- Poetry 1.8+
- Docker Engine e Docker SDK acessivel pelo worker
- PostgreSQL
- RabbitMQ

Para executar somente o esqueleto local, Python e Poetry sao suficientes. Para executar o fluxo completo, Docker, PostgreSQL e RabbitMQ tambem precisam estar disponiveis.

## Configuracao

Copie o arquivo de exemplo e ajuste os valores para o ambiente:

```bash
cp .env.example .env
```

## Desenvolvimento local

Instale as dependencias:

```bash
make install
```

Inicie a aplicacao com hot reload:

```bash
make dev
```

Ou execute sem hot reload:

```bash
make run
```

Endpoints disponiveis no esqueleto atual:

```text
GET /health
GET /ready
GET /metrics
```

## Docker Compose

O Compose deste diretório cobre apenas a instrumentação do serviço com o Grafana Alloy, e espera que os destinos externos de Loki, Prometheus e Tempo estejam configurados em `LOKI_URL`, `PROMETHEUS_URL` e `TEMPO_URL`.

Ele **não** sobe o RabbitMQ nem concede acesso ao daemon do Docker, que o worker exige na subida. Para rodar o serviço de fato, use o Compose da raíz:

```bash
docker compose -f ../deploy/docker-compose.yml up -d worker
```

O health fica em `http://localhost:8002/health`. O pré-requisito de acesso ao Docker está em [docs/instalacao.md](../docs/instalacao.md) secao 2.1.

## Qualidade e testes

```bash
make lint
make typecheck
make test
```

Para formatar o codigo:

```bash
make format
```

## Observabilidade

O worker deve emitir logs e metricas com o `job_id` como identificador de correlacao. As metricas especificas do fluxo devem incluir, pelo menos:

- duracao da execucao por job;
- quantidade de sucessos, erros e timeouts;
- quantidade de containers ativos;
- quantidade de retries por tipo de falha.

Erros do codigo gerado, violacoes de assercoes invariantes, timeouts e falhas de infraestrutura precisam permanecer distintos no resultado publicado. Uma regra inviavel por orcamento nao e um erro de execucao.

## Estrutura

```text
worker/
├── app/
│   ├── core/              # logging e metricas
│   ├── mensageria/        # conexao com o RabbitMQ e fila de execucao
│   ├── sandbox/           # acesso ao daemon do Docker
│   ├── config.py          # configuracao por ambiente
│   └── main.py            # health, readiness e metricas
├── tests/                 # testes automatizados
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── run.py
```

## Referencias

- [Arquitetura do Synapse](../docs/ARCHITECTURE.md)
- [Secao do Worker na arquitetura](../docs/ARCHITECTURE.md#34-worker-de-execucao)
- [Sandbox de execucao](../docs/ARCHITECTURE.md#7-sandbox-de-execucao)

## Regras base de comissionamento

A apuração determinística das regras 5a a 5g da Dom Rock está em `app/sandbox/regras_base.py`. A função `apurar` consome somente as tabelas canônicas (`rh`, `vendas`, `comissionamento` e `eventos_rh`) e não lê planilhas de origem. O resultado é ordenado por matrícula e inclui referências às linhas de entrada, eventos e chaves de percentual usados no cálculo. Para cargo 150, `linhas_vendas` referencia todas as vendas da loja que compõem a base do gerente; para os demais cargos, referencia somente as vendas da própria matrícula. As janelas `data_inicio`/`data_fim` de afastamentos e férias são consumidas como intervalos fechados, conforme a semântica da T-028.

As premissas de cargo 150, vendas órfãs, licença-maternidade e o caso de gerente rateado entre lojas estão registradas em [`DEC-090`](../docs/decisoes/dec-090.md).

## Asserções invariantes (T-031)

Toda chamada a `apurar` finaliza com as três asserções internas, sem baseline nem orçamento. Uma violação interrompe a apuração com `AssercaoVioladaError` e desfecho estruturado; não é um veredito de inviabilidade. A interface de tabela da T-030 permanece compatível. Consulte [integração, saída e testes](docs/t031-assercoes.md), incluindo o ponto de integração para o futuro executor de containers.

## Baselines congelados (T-032)

Os cinco baselines de agosto a dezembro de 2025 ficam em `sandbox/data/domrock/baselines/`, com total, lojas, matrículas e asserções no próprio JSONL de cada mês. **Baseline não é gabarito.** A preparação inclui as regras históricas de todos os meses e preserva os eventos da T-028. Confira os bytes com `poetry run python -m scripts.build_baselines --check`. Veja [totais, formato, premissas e reprodução](docs/t032-baselines.md).

## Decomposição do resultado (T-035)

`app/sandbox/resultado.py` agrega o retorno da função gerada (por matrícula) na saída do contrato da T-034: `totais`, `assercoes` e a `decomposicao` da **diferença** em relação ao baseline, por elemento da regra, loja, marca, cargo e competência. Somar qualquer quebra dá `totais.diferenca_abs`, e zero é preservado — elemento que se cancela, competência simulada sem efeito e loja não afetada aparecem com `0.0`, porque ausência diria outra coisa. `totais` sai **sem `orcamento`**: quem o acrescenta, junto do veredito, é o worker fora do container (T-066). Veja [quebras, arredondamento, erros e limites](docs/t035-decomposicao.md).

## Imagem do sandbox (T-033)

`sandbox/Dockerfile` constrói a imagem onde o código gerado roda: sem rede, somente-leitura, usuário não-root, com pandas, as bases, os eventos de RH e os baselines congelados embutidos. O código chega pelo stdin como JSON e o resultado decomposto volta pelo stdout, num envelope de uma linha; **o orçamento nunca entra**. `app/sandbox/executor.py` é o ponto de entrada, `harness.py` o único módulo que executa código gerado (o processo do worker nunca o importa) e `carga.py` monta as bases com tipos explícitos. Build da raiz do monorepo: `docker build -f worker/sandbox/Dockerfile -t synapse-sandbox:local .`. Veja [o que entra na imagem, o envelope, as defesas e as pendências para a T-064](docs/t033-imagem-sandbox.md).
