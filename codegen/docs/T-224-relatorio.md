# T-224 — correção do PR e relatório de verificação

## Base e aplicação do pacote

Revisão realizada em 19/10/2026 sobre os dois ZIPs fornecidos. A base é o commit
`3454a48` de `synapse-commit.zip`, acrescido dos arquivos de `synapse_T-224_alteracoes.zip`.
O estado remoto do GitHub não foi consultado nem alterado.

O ZIP corrigido contém **20 arquivos novos ou modificados em relação ao develop fornecido**,
todos sob `codegen/`. É a implementação completa da T-224 corrigida, não apenas um patch
incremental sobre o primeiro ZIP. Pode ser aplicado tanto à base fornecida quanto à branch
`feature/t-224-historico-reextracao` com aquele primeiro pacote já aplicado.

1. Na branch da tarefa, preserve eventuais alterações locais posteriores ao ZIP enviado.
2. Extraia o ZIP na **raiz do repositório**, mesclando a pasta `codegen/` e substituindo os
   arquivos correspondentes. Não extraia dentro de `codegen/`.
3. Confira `git diff`, execute `cd codegen && make pre-commit` e atualize o mesmo PR.

Não há arquivos para excluir, migrações, novas dependências de projeto, alterações de eventos
ou mudanças nos outros serviços. O pacote não inclui `.git`, ambientes virtuais ou credenciais.

## Correções dos dois problemas apontados

### Substituição sem lastro preserva o elemento inteiro

Uma substituição com `valor_sem_lastro` é recusada antes de alterar a lista. O elemento,
inclusive suas condições e valores, permanece como estava naquele ponto do lote.
A operação gera `DiagnosticoOperacao(indice, "valor_sem_lastro")`, contado pela instrumentação
existente. Nenhum motivo é inserido na representação ou no contrato de evento.

O trecho isolado da correção não substitui mais a descrição original. Isso vale também
para uma resposta do modelo que invente uma alteração a partir de uma confirmação como
“Está certo assim, pode seguir.”. O prompt pede lista vazia quando não há mudança solicitada.

### Correção parcial aceita valores preservados do elemento atual

A montagem recebe opcionalmente o elemento atual **apenas na substituição**:

- Números mantidos na descrição podem vir da descrição daquele elemento atual.
- Números novos continuam exigindo lastro no trecho da correção corrente.
- Um campo numérico de construto habilitado só aproveita o valor existente quando é o mesmo
  campo, com o mesmo valor, no mesmo construto. Valores alterados passam por `conferir_numero`.
- O trecho da operação e o trecho do elemento continuam precisando existir na correção atual.
- Histórico e outros elementos não se tornam fonte de lastro. Uma inclusão não herda valores.
- A extração inicial não fornece `elemento_atual` e mantém seu comportamento anterior.

Exemplo coberto por testes do aplicador, corpus com modelo falso e consumer/grafo reais:

| Regra atual | Correção / resposta candidata | Resultado |
| --- | --- | --- |
| Bônus de R$ 500 para vendas acima de R$ 10.000 no mês | “o bônus passa para 600 reais”, candidato completo com 600 e 10.000 | Bônus de 600, preservando a condição de 10.000 e o período mensal |
| Mesma regra | Correção menciona 600, modelo propõe 700 | Elemento original integral, diagnóstico `valor_sem_lastro` |
| Mesma regra | Confirmação sem número, modelo propõe bônus de 600 | Elemento original integral, diagnóstico `valor_sem_lastro` |
| Mesma regra | 700 aparece apenas em uma correção histórica não aplicada | Elemento original integral, diagnóstico `valor_sem_lastro` |

Quando os valores conferem, mas o construto não está habilitado, continua sendo produzido
`generico` com a **paráfrase completa conferida**. Para uma inclusão sem lastro, permanece o
rebaixamento existente para genérico com o trecho literal da operação, sem o número inventado;
essa inclusão não substitui um elemento anterior.

A conferência usa o mecanismo lexical e numérico da T-210. Não introduz conversão de números
por extenso nem pretende provar equivalência semântica completa de paráfrases livres.

## Demais entregas T-224 preservadas e verificadas

- Leitura de histórico somente por `SELECT`, a partir da submissão corrente, seguindo a cadeia
  de rodadas do mesmo job; cinco anteriores mais recentes, em ordem cronológica, inclusive falhas.
- Textos e conflitos históricos no compartimento de dados não confiáveis; histórico vazio sem erro.
- Seis tipos de operação com trecho literal obrigatório, incluindo remoções e parâmetros.
- Orçamento, meta e período continuam protegidos pela validação determinística existente.
- Motivos fechados nas métricas, sem mudanças no nome ou na forma do contador.
- Corpus ampliado de cinco para nove casos; testes do aplicador, modelo falso, prompt e grafo.
- Corrigidos também os problemas de lint/formatação do pacote original, incluindo linha longa
  no prompt e variável ambígua no teste de observabilidade.

## Ambiente e comandos executados

Python 3.12.14. As dependências foram instaladas, em ambiente virtual isolado, pelas versões
fixadas em `requirements-dev.txt`, mais Poetry. Como o ambiente não tinha `libpq`, foi instalado
`psycopg-binary==3.3.6` somente no ambiente de testes, na mesma versão do driver existente.
Nenhum manifesto foi alterado. Não foram usados shims ou substitutos de bibliotecas.

Comandos a partir de `codegen/`, com esse ambiente virtual ativado:

| Comando | Resultado |
| --- | --- |
| `python scripts/preparar_contratos.py` | Aprovado; contratos preparados pelo script do projeto |
| `pytest -q tests/app/extracao/test_correcao.py` antes da correção de produção | 9 falhas esperadas e 85 aprovações, reproduzindo a perda de conteúdo e a rejeição da correção parcial |
| `pytest -q tests/app/extracao/test_correcao.py tests/app/graph/test_reextracao.py` após a correção inicial | 128 aprovados |
| `pytest -q tests/app/extracao/test_correcao.py tests/app/graph/test_reextracao.py tests/app/extracao/test_corpus_reextracao*.py` após ampliar corpus e testes | 152 aprovados, 6 pulados por ausência de `GOOGLE_API_KEY` |
| `make pre-commit` | **Aprovado**: Ruff, formatação, mypy sem problemas em 82 arquivos e **1.093 testes aprovados, 86 pulados** |
| `make lint` | Ruff aprovado; Bandit retorna quatro B101 de severidade baixa já existentes no develop |
| `bandit -r app/ -f json` sobre a base develop fornecida | Confirma os mesmos quatro B101, nos mesmos arquivos e linhas |
| `git diff --check` | Aprovado |

O alvo `make pre-commit` deste repositório não chama Bandit. Os quatro avisos de `make lint`
são `assert_used` em `app/extracao/lastro.py:70`, `lastro.py:130`, `motor.py:89` e
`vocabulario.py:69`. Esses arquivos não foram alterados nesta entrega. Não houve supressão
dos avisos nem mudanças fora do escopo para tornar esse alvo verde.

## Prova vermelho → verde

Além das nove falhas reproduzidas antes da correção, foram aplicadas mutações temporárias ao
código, executados os testes correspondentes e restaurados todos os arquivos em seguida:

| Defeito reintroduzido temporariamente | Resultado vermelho |
| --- | --- |
| Restaurar aplicador do ZIP recusado e montagem do develop | 21 falhas de regressão: aplicador, campos numéricos, corpus e grafo |
| Inventar histórico quando a cadeia está vazia | 1 falha |
| Deixar de passar histórico pelo nó | 1 falha |
| Aumentar indevidamente o limite de cinco para seis | 2 falhas |
| Retirar o filtro SQL por job dos ancestrais | 1 falha na proteção da consulta |
| Retirar a conferência do trecho da operação | 24 falhas |
| Retirar a conferência numérica de campos/parâmetros | 4 falhas |
| Mover os dados para fora do compartimento não confiável | 1 falha |
| Retirar o incremento do contador no caminho do grafo | 1 falha |

As mutações não fazem parte da entrega. Após a restauração, o gate completo foi executado
novamente. A prova de isolamento da consulta usa o banco falso e a inspeção do SQL, não uma
execução contra PostgreSQL real.

## Observabilidade e limites de verificação

**Verificado:** consumer, roteador, grafo, nó e aplicador reais, com banco, broker/produtores e
modelo falsos. Os testes capturam logs pela preparação de fila e formatação JSON, validam-nos
contra `contracts/observability/log.schema.json`, verificam correlação por job e limpeza de
contexto, e procuram conteúdo proibido. Há cobertura de sucesso, falha, cancelamento e reentrega.
Os testes novos conferem também a proposta completa publicada nos cenários de bônus parcial
e substituição recusada, incluindo a preservação dos parâmetros.

**Métricas verificadas:** deltas de execução, falhas, duração, elementos e rebaixamentos pelo
endpoint HTTP `/metrics`, usando cliente ASGI, depois de exercitar o fluxo. Os motivos
`operacao_sem_trecho` e `valor_sem_lastro` são observados nesse caminho. Os textos da correção,
do histórico e da resposta não aparecem nos logs capturados.

**Não executado:** corpus com modelo real, por ausência de `GOOGLE_API_KEY` (seis casos T-224
pulados); integrações que exigem PostgreSQL/RabbitMQ/serviços externos; validação da permissão
SELECT em banco real; execução do loop completo por Docker Compose; coleta externa por
Prometheus/Alloy/Grafana e exportação de traces. A suíte completa informa 86 testes pulados
por suas condições de ambiente. Nenhum caso foi silenciado ou marcado como skip nesta revisão.

Para executar o corpus real em ambiente com credencial configurada:

```bash
cd codegen
poetry run pytest -q -m llm tests/app/extracao/test_corpus_reextracao.py
```

A correção dos dois bloqueios do review e o gate local estão comprovados. A validação com
modelo real e infraestrutura permanece pendente; não se declara o DoD externo integralmente
concluído nem aprovação do PR.
