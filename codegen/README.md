# codegen

Processo Python responsável pela geração assistida do Synapse. A comunicação de negócio
com os outros serviços ocorrerá somente pelo RabbitMQ; a aplicação FastAPI existe para
observabilidade operacional, não como API de negócio.

## Endpoints

| Método | Caminho | Finalidade |
| --- | --- | --- |
| GET | `/health` | Verifica se o processo está disponível. |
| GET | `/metrics` | Expõe métricas no formato de texto do Prometheus. |

Não há outros endpoints, documentação OpenAPI ou rotas de negócio.

## Execução local

Requer Python 3.12 e Poetry:

```bash
poetry install
make dev
```

O serviço fica disponível em `http://localhost:8000`. Os testes e verificações de
qualidade são executados por:

```bash
make pre-commit
```

## Docker Compose

Na raiz do repositório:

```bash
docker compose -f deploy/docker-compose.yml up -d --build --wait codegen
```

O serviço é publicado em `http://localhost:8001`. Os logs são objetos JSON emitidos
somente no stdout, com `service.name` igual a `synapse-codegen`.

## Estrutura

```text
app/
  main.py          casca FastAPI operacional
  mensageria/      integração RabbitMQ das tarefas futuras
  nos/             nós LangGraph das tarefas futuras
  core/            logs e métricas transversais
tests/             verificações da casca e da observabilidade
```
