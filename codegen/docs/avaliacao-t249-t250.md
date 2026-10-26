# T-249 / T-250 — Relatório de avaliação da geração de código

Data: 18/10/2026  
Componente: `codegen`  
Fonte de verdade: casos e referências da T-245 em `worker/tests/fixtures/casos_geracao/`.

## Mudanças do prompt

- **T-249 (`faixa_valor`)**: o prompt instrui consolidar `vlr_venda` por `matricula` e `competencia`, aplicar uma única faixa por pessoa dentro do núcleo, tratar o limite superior da última faixa aberta como sentinela, somar o bônus uma vez por competência e atribuir o delta a cada `elem.N` sem misturá-lo ao delta de `nucleo.percentual`.
- **T-250 (`condicao_limiar`)**: o prompt instrui agregar `venda_total` na dimensão declarada (`matricula`, `loja`, `marca` ou `rede`) **por competência**, comparar com o operador exato, aplicar o núcleo somente onde a condição vale e declarar o elemento da condição sem atribuir-lhe contribuição financeira.
- As orientações entram **somente** se o construto correspondente constar nas `especificacoes`. A orientação existente para núcleo, gerente e `generico` foi preservada. Contratos, worker e configuração do modelo não foram modificados.

## Estado das rodadas com LLM real + avaliador do worker

**NÃO EXECUTADAS.** Não há `GOOGLE_API_KEY` configurada, Poetry ou Docker acessível no ambiente desta entrega. Portanto não houve geração real, execução no sandbox, conferência de cobertura do código gerado nem validação numérica da decomposição. **As tarefas T-249 e T-250 ainda não cumprem os critérios de aceitação nem a DoD.** Um teste unitário de construção de prompt não substitui a prova de três gerações consecutivas.

`prompt_id`: o identificador SHA-256 truncado que `scripts.gerar_casos_geracao` emite para o *prompt efetivamente enviado*; não há `prompt_id` de rodada sem chamada ao modelo. `—` significa ausência de execução, **não** aprovação.

| Caso da T-245 | Papel na avaliação | Prompt ID usado | Rodada 1 | Rodada 2 | Rodada 3 | Cobertura/elementos e quebra por elemento |
| --- | --- | --- | --- | --- | --- | --- |
| `faixa-valor-dezembro` | **T-249** | — | não executada | não executada | não executada | não avaliada |
| `condicao-limiar-loja` | **T-250** | — | não executada | não executada | não executada | não avaliada |
| `nucleo-controle` | regressão: núcleo | — | não executada | não executada | não executada | não avaliada |
| `generico-admissao` | regressão: genérico | — | não executada | não executada | não executada | não avaliada |
| `generico-aniversario-loja` | regressão: falha esperada | — | não executada | não executada | não executada | não avaliada |
| `bonus-fixo-lista-e-filtro` | regressão: bônus fixo | — | não executada | não executada | não executada | não avaliada |
| `janela-datas-black-friday` | regressão: janela | — | não executada | não executada | não executada | não avaliada |
| `exclusao-gerente` | regressão: exclusão | — | não executada | não executada | não executada | não avaliada |
| `combinado-elementos` | **regressão combinada** | — | não executada | não executada | não executada | não avaliada |

A aprovação do caso que **espera uma falha** depende do desfecho `falhou_como_esperado` do avaliador, não de um cálculo fictício. Para os demais, confirmar `bate`, cobertura completa e diferenças nulas (dentro da tolerância do harness) também na decomposição por elemento. A comprovação de três gerações seguidas requer todos os casos exigidos aprovados em **três chamadas reais distintas**.

## Verificações locais realizadas

| Comando ou verificação | Resultado |
| --- | --- |
| `python -m compileall` dos dois arquivos Python alterados | passou |
| `pytest -q tests/app/prompts/test_geracao_codigo.py` em ambiente isolado de teste com substituto **temporário** de `simplejson` | **60 testes passaram** (inclui teste de consistência `regrafn.md` e cobertura dos nove casos no *prompt*) |
| Remover temporariamente a injeção das duas orientações e executar os dois testes novos específicos | **2 falhas esperadas**; restauração e nova execução: 60 passaram |
| Comparação byte a byte do prompt anterior versus novo para os seis casos sem `faixa_valor` nem `condicao_limiar` (serializador temporário comum aos dois) | **iguais nos seis casos**; apenas `faixa-valor-dezembro`, `condicao-limiar-loja` e `combinado-elementos` mudaram |
| `make pre-commit` | **não executou o gate**: `poetry: No such file or directory` (erro 127) |
| `scripts.gerar_casos_geracao` com modelo real | não executado: faltam dependências do codegen e `GOOGLE_API_KEY` |
| `scripts.avaliar_geracao` no sandbox | não executado: Docker indisponível |

O substituto de `simplejson` é exclusivamente do ambiente de teste e **não faz parte dos arquivos entregues**. Esses testes validam presença, isolamento, invariantes e consistência do prompt; não provam que o modelo gerará código correto. O `make pre-commit` oficial precisa ser executado com as dependências instaladas.

## Execução necessária para conclusão (na raiz do repositório)

Instale as dependências dos dois componentes, configure `GOOGLE_API_KEY` e garanta que o Docker esteja em execução. Os arquivos gerados, respostas, códigos e logs ficam fora do PR.

```bash
(cd codegen && poetry install && make pre-commit)
(cd worker && poetry install)
docker build -f worker/sandbox/Dockerfile -t synapse-sandbox:t249250 .

mkdir -p .tmp/avaliacao-t249-t250
SAIDA="$(pwd)/.tmp/avaliacao-t249-t250"
for RODADA in 1 2 3; do
  mkdir -p "${SAIDA}/rodada-${RODADA}"
  (cd codegen && poetry run python -m scripts.gerar_casos_geracao \
    --saida "${SAIDA}/rodada-${RODADA}" \
    > "${SAIDA}/rodada-${RODADA}/geracao.jsonl") || exit 1
  (cd worker && poetry run python -m scripts.avaliar_geracao \
    --codigo "${SAIDA}/rodada-${RODADA}" \
    --imagem synapse-sandbox:t249250 --json \
    > "${SAIDA}/rodada-${RODADA}/avaliacao.json") || exit 1
done
```

O gerador roda **todos os casos** da T-245 por padrão. Cada `geracao.jsonl` inclui `caso`, `prompt_id` e o desfecho de geração, sem resposta do modelo; `avaliacao.json` inclui o resultado por caso, ausência de elementos e diferenças por elemento. Antes do PR, conferir manualmente a matriz de casos/rodadas, preencher a tabela acima com os **IDs realmente emitidos** e os resultados, e incluir somente o relatório sanitizado: **não versionar** os diretórios `.tmp`, o código gerado ou as respostas do provedor. Caso alguma rodada falhe, ajustar o prompt dentro do escopo, recomeçar a contagem das três rodadas consecutivas e reavaliar os casos de regressão e o combinado.

Se as três aprovações não forem alcançadas após os ajustes, registrar o achado como decisão de escopo no épico **E12**, sem anunciar a tarefa como concluída. A publicação dessa decisão depende do mantenedor do backlog.
