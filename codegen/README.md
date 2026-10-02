# codegen

Processo Python responsável pela geração assistida do Synapse. A lógica de negócio roda como um grafo LangGraph; a comunicação com os outros serviços ocorre pelo RabbitMQ. FastAPI expõe a observabilidade operacional.

## Stack

| Camada | Tecnologia |
| --- | --- |
| Runtime | Python 3.12 |
| Web operacional | FastAPI, Uvicorn |
| Grafo | LangGraph assíncrono, com `AsyncPostgresSaver` |
| Settings | Pydantic Settings |
| Artefatos | PostgreSQL via SQLAlchemy 2 e asyncpg |
| Checkpoints | PostgreSQL via psycopg 3 e psycopg-pool |
| Mensageria | RabbitMQ via aio-pika |
| Telemetria | Logs JSON, prometheus-client e OpenTelemetry |
| Qualidade | Ruff, mypy, Bandit e pytest |

As migrations de domínio pertencem à API, via Liquibase. As quatro tabelas internas de checkpoint são criadas por `AsyncPostgresSaver.setup()` no início da aplicação.

## Endpoints

| Método | Caminho | Finalidade |
| --- | --- | --- |
| GET | `/health` | Disponibilidade do processo |
| GET | `/metrics` | Métricas Prometheus |

Não há interface HTTP de negócio entre o codegen, a API e o worker.

## Mensageria e inicialização

A montagem padrão em `app/main.py::criar_aplicacao_padrao()` conecta o `GraphRouter` ao grafo. O lifespan prepara conexões, checkpointer e producers e inicia os consumers reais.

- `regra-submetida` inicia ou continua um ciclo.
- `simulacao-concluida.codegen` retoma a espera pela execução, independentemente do consumer da API.
- `parametros-confirmados` tem fila e publicador na API, mas seu consumo ainda não está implementado no codegen.

Topologia, confirmações e integração estão em [Mensageria](docs/mensageria.md); o comportamento de retomada está em [Retomada após execução](docs/retomada-apos-execucao.md).

## Grafo implementado

```text
load_rule → code_generation → persist_response → extract_code
→ dispatch_execution → await_execution → decision
                                        ├─ suggest_adaptation → END
                                        └─ END
```

O grafo recebe referências de uma regra já estruturada. Não há nó ativo de extração inicial de texto ou áudio. A validação de domínio existente é usada no caminho de adaptação; sua aplicação no pipeline principal e o loop do chatbot são trabalho da Sprint 2.

O código gerado é persistido e delegado ao worker, que o executa em sandbox. O codegen não executa esse código nem produz números de simulação pela LLM.

A alternativa automática tem recorte de núcleo, sem especificações, e uma tentativa por job. A API persiste a versão proposta e inicia outro ciclo para executá-la antes de uma aceitação.

## Estado e persistência

O estado ativo é o `AgentState` definido em `app/graph/core/state.py`. Ele guarda identificação do ciclo, competências, orçamento em representação decimal textual, referências de artefatos e os dados temporários necessários aos nós. `app/estado.py::EstadoGrafo` não é o estado usado pelo engine atual.

O orçamento já é enviado pela API em `regra-submetida`. O campo é opcional no schema por compatibilidade; quando ausente, não pode ser buscado em `jobs`, pois o codegen não possui essa permissão. A delegação ao worker exige esse valor.

O `thread_id` é `job_id:regra_id`, produzido por `thread_do_ciclo`. Há compatibilidade com checkpoints antigos por job somente quando correspondem à mesma regra. Sugestões geram ciclos separados.

A pausa de execução usa `interrupt()`; a retomada usa `Command(resume=...)`. Um checkpoint já existente não deve ser reiniciado com uma entrada nova. O tratamento distingue resultado antecipado, ausência de checkpoint, ciclo concluído e retomada efetiva.

Os identificadores de eventos de trilha são determinísticos por job, nó e artefato. Checkpoints finais também participam da deduplicação; sua limpeza ainda não está implementada e precisa preservar essa proteção.

## Contratos

`scripts/preparar_contratos.py` incorpora os schemas do monorepo ao componente, preservando os diretórios. O runtime lê essa cópia local, sem depender da raiz do repositório. No Docker, os contratos entram na imagem durante o build.

A representação da regra é definida pelos [contratos de domínio](../contracts/domain/README.md). Usar o schema completo não comprova que a geração já implementa corretamente todos os construtos; essa prova faz parte da Sprint 2.

## Execução e verificação

Requer Python 3.12 e Poetry:

```bash
poetry install
poetry run python scripts/preparar_contratos.py
make dev
```

O serviço fica em `http://localhost:8000`. Execute o gate do componente:

```bash
./verify.sh
```

Sem `make`, prepare os contratos e execute `poetry run pytest`, `poetry run ruff check app/`, `poetry run ruff format --check app/`, `poetry run mypy app/` e `poetry run bandit -r app/`.

Na raiz do repositório, para Compose:

```bash
docker compose -f deploy/docker-compose.yml up -d --build --wait codegen
```

O Compose publica o serviço em `http://localhost:8001`. Logs são JSON no stdout, com `service.name=synapse-codegen`; não devem incluir prompts, transcrições, código ou linhas de dataset.

## Organização

- `app/main.py`: aplicação operacional e montagem das integrações.
- `app/config.py`: settings.
- `app/mensageria/`: transporte RabbitMQ e roteamento.
- `app/graph/entrypoint.py`: fronteira pública do grafo.
- `app/graph/core/`: engine, estado, checkpointer e registro de modelos.
- `app/graph/nodes/`: um arquivo por nó.
- `app/graph/prompts/`: prompts centralizados.
- `app/core/`: infraestrutura transversal de logs e métricas.
- `tests/`: verificações do componente.

`app/core/` e `app/graph/core/` são camadas distintas. Convenções do grafo estão em [.agents/skills/graph/SKILL.md](.agents/skills/graph/SKILL.md). O fluxo aprovado para a próxima entrega está em [Fluxo e decisões da Sprint 2](../docs/FLUXO-SPRINT-2.md).
