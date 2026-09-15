# codegen

Processo Python responsável pela geração assistida do Synapse. A comunicação de negócio
com os outros serviços ocorre somente pelo RabbitMQ; a aplicação FastAPI existe para
observabilidade operacional, não como API de negócio.

## Endpoints

| Método | Caminho | Finalidade |
| --- | --- | --- |
| GET | `/health` | Verifica se o processo está disponível. |
| GET | `/metrics` | Expõe métricas no formato de texto do Prometheus. |

Não há outros endpoints, documentação OpenAPI ou rotas de negócio.

## Mensageria

Os seis DTOs, consumers/producers, política de confirmações, configuração do broker
e testes reais do compose estão descritos em [Mensageria T-049](docs/mensageria.md).
O lifespan declara a topologia e disponibiliza producers; inicia o consumo quando
`criar_aplicacao(roteador=...)` recebe a integração real com o grafo. Sem roteador,
as mensagens permanecem no broker e o processo registra um aviso.

## Execução local

Requer Python 3.12 e Poetry:

```bash
poetry install
poetry run python scripts/preparar_contratos.py
make dev
```

O serviço fica disponível em `http://localhost:8000`. Os testes e verificações de
qualidade são executados por:

```bash
make pre-commit
```

Sem `make`, prepare os contratos com o comando acima e execute `poetry run pytest`,
`poetry run ruff check app/`, `poetry run ruff format --check app/`,
`poetry run mypy app/` e `poetry run bandit -r app/`.

## Estado do grafo

`app/estado.py` define `EstadoGrafo` como modelo Pydantic, com validação em runtime.
`job_id` (UUID), `origem` e `competencias` são obrigatórios: são os dados comuns
do evento `regra-submetida`. O nome plural preserva o contrato: um job abrange uma
lista não vazia de meses `AAAA-MM`, inclusive meses não contíguos.

Orçamento, representação da regra, código, referência do resultado e veredito
começam em `None`. O orçamento existe no job da API, mas não vem no evento inicial;
seu carregamento pertence à integração. A referência do resultado é o UUID de
`resultados_simulacao`, sem totais ou linhas de bases. `codigo_gerado` é texto
interno, nunca executado pelo codegen nem enviado em uma mensagem de negócio.

O histórico começa com uma lista independente por instância. Cada item é uma
proposta no mesmo formato `RepresentacaoRegra` da regra principal. Esta é a forma
mínima do histórico de sugestões da US03; não define decisões do usuário, fluxos
de adaptação ou resultados de novas simulações.

`RepresentacaoRegra` envolve a estrutura original da T-004 e a valida diretamente
com `jsonschema` (draft 2020-12, incluindo formatos e referências locais).
Não há outro schema da regra. `scripts/preparar_contratos.py` copia todos os
`contracts/**/*.schema.json` para `codegen/contracts/`, preservando diretórios,
um artefato ignorado pelo Git. A descoberta recursiva inclui eventos, comandos
(armazenados em `events/` pela T-003) e suas referências sem listas de arquivos.
Os alvos de instalação, execução e testes do Makefile fazem essa preparação.
No Docker, o `COPY contracts ./contracts` existente incorpora os schemas na imagem.
Runtime lê somente essa cópia do componente, sem consultar a raiz do monorepo.
Todos os schemas de domínio incorporados são registrados dinamicamente; apenas
`representacao-regra.schema.json` identifica o schema raiz. Os objetos permanecem
extensíveis conforme as [convenções canônicas da T-004](../contracts/domain/README.md#convenções).

Ao ler uma regra JSON, use `json.loads(texto, parse_float=Decimal)` para preservar
os números como decimais desde a entrada. O modelo recusa `float`; aceita números
inteiros e `Decimal`, e datas ISO ou objetos `date`. Não interpreta textos
arbitrários como datas. `para_contrato()` fornece a estrutura para validação JSON
Schema: datas nativas viram ISO e `Decimal` continua numérico. Cada chamada revalida
a estrutura atual, inclusive mutações aninhadas. Falhas estruturais e de contrato
produzem erros sanitizados, sem valores ou caminhos extraídos do conteúdo da regra.

```python
from decimal import Decimal
from uuid import UUID

from app.estado import EstadoGrafo, desserializar_estado, serializar_estado

estado = EstadoGrafo(
    job_id=UUID("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021"),
    origem="voz",
    competencias=["2025-08", "2025-11"],
    orcamento=Decimal("1234567890.123456789"),
)
tipo, dados = serializar_estado(estado)
restaurado = desserializar_estado((tipo, dados))
assert restaurado == estado
```

A representação persistível é `("msgpack", bytes)`, produzida pelo
`JsonPlusSerializer` de `langgraph-checkpoint`, com pickle desabilitado e sem
permitir reconstrução de classes da aplicação. O payload contém o dicionário
`model_dump(mode="python")`, preservando `Decimal`, `date` e `UUID` com os codecs
oficiais. A desserialização revalida o estado e a T-004. A serialização também
revalida alterações em listas e objetos aninhados. Use essas funções para o
round-trip; `model_dump_json()` converte Decimal em texto e não é esse formato.

Os testes cobrem a camada de serialização usada pelo checkpointer e a retomada
em outro processo. A conexão PostgreSQL, o grafo e seus canais ficam para as
respectivas tarefas de integração; não são implementados pelo schema de estado.

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
