# T-247 e T-248 — avaliação da geração (`bonus_fixo` e `janela_datas`)

## Estado da verificação

**Implementação do prompt e testes estáticos: realizada. Prova empírica exigida pelas tarefas: pendente.**

Data do registro: 18/10/2026. Neste ambiente não há `GOOGLE_API_KEY`, Poetry,
Docker nem acesso a um índice de pacotes; por isso **não foi feita nenhuma chamada ao modelo real
nem execução do código gerado no sandbox**. Não há três aprovações consecutivas para nenhum
caso, nem prova de que a modificação preserve os resultados antes aprovados. As T-247 e
T-248 **não satisfazem a definição de concluído** até executar as rodadas abaixo.

O prompt usa as representações dos casos da T-245 como fonte de semântica. O construto
`bonus_fixo` recebe instruções sobre granularidade matrícula/competência, quadro do mês,
lista, filtro cadastral e deltas separados. O construto `janela_datas` recebe instruções
sobre `data_venda` inclusiva e não nula, competência independente de data, percentual sobre
`vlr_venda`, agrupamento prévio e deltas separados. Essas orientações são adicionadas somente
se o **construto** existe em `especificacoes`, evitando regressão de prompt nos casos que não
o usam. O efeito `bonus_fixo` de uma `faixa_valor` não é confundido com o construto homônimo.

## Relatório de rodadas (modelo real e avaliador do worker)

`prompt_id` é o hash de 12 caracteres produzido por
`codegen/scripts/gerar_casos_geracao.py`, por **caso**, no início de cada geração. Sem
invocação real, não há identificador de prompt *usado*; os campos devem ser preenchidos
com o JSON emitido pelo script de geração. `Pendente` **não significa aprovado**.

| Caso | Escopo | Prompt ID usado | Rodada 1 | Rodada 2 | Rodada 3 |
| --- | --- | --- | --- | --- | --- |
| `nucleo-controle` | regressão núcleo | — | Pendente | Pendente | Pendente |
| `generico-admissao` | regressão `generico` | — | Pendente | Pendente | Pendente |
| `generico-aniversario-loja` | regressão falha esperada | — | Pendente | Pendente | Pendente |
| `exclusao-gerente` | regressão T-245 | — | Pendente | Pendente | Pendente |
| `faixa-valor-dezembro` | regressão T-245 | — | Pendente | Pendente | Pendente |
| `condicao-limiar-loja` | regressão T-245 | — | Pendente | Pendente | Pendente |
| `bonus-fixo-lista-e-filtro` | **T-247** | — | Pendente | Pendente | Pendente |
| `janela-datas-black-friday` | **T-248** | — | Pendente | Pendente | Pendente |
| `combinado-elementos` | regressão / combinado | — | Pendente | Pendente | Pendente |

Em cada rodada, anotar `desfecho` e `passou` do JSON do avaliador: `bate` ou
`falhou_como_esperado` (somente quando a referência exige a falha), além da ausência de
`elementos_ausentes` e `elementos_fora_da_regra`. Para casos de números, a comparação é
feita pelo avaliador no total e na quebra por elemento, com a tolerância dele.

**Critério de aprovação:** três gerações *independentes e consecutivas* de cada caso,
seguidas da avaliação no worker, com a cobertura completa e todos os nove casos aprovados
em cada rodada. Em caso de divergência, ajustar apenas o prompt/configuração e reiniciar a
contagem de três rodadas; registrar os IDs dos novos prompts. Não misturar artefatos de
rodadas diferentes. O relatório de PR não deve incluir `regra.py`, prompt completo nem
respostas do provedor.

## Como executar as três rodadas em ambiente configurado

A partir da **raiz do monorepo**, com `poetry` configurado para Python 3.12/3.13, chave
`GOOGLE_API_KEY` disponível ao processo do codegen e Docker operante:

```bash
# Build da imagem de execução, na raiz do monorepo.
docker build -f worker/sandbox/Dockerfile -t synapse-sandbox:local .

# No codegen, confirme antes o gate e a versão de contratos.
cd codegen
make pre-commit

# Execute exatamente três gerações independentes, uma pasta por rodada.
# O gerador imprime APENAS registros JSON (caso, prompt_id, finish_reason, ok).
mkdir -p ../.avaliacao-t247-t248
for rodada in 1 2 3; do
    mkdir -p "../.avaliacao-t247-t248/rodada-$rodada"
    poetry run python -m scripts.gerar_casos_geracao \
        --saida "../.avaliacao-t247-t248/rodada-$rodada" \
        > "../.avaliacao-t247-t248/geracao-$rodada.jsonl" || break
    (
        cd ../worker
        poetry run python -m scripts.avaliar_geracao \
            --codigo "../.avaliacao-t247-t248/rodada-$rodada" --json \
            > "../.avaliacao-t247-t248/avaliacao-$rodada.json"
    ) || break
done

# Conferir as referências congeladas da T-245, sem regravar esperados.
cd ../worker
poetry run python -m scripts.gravar_esperado --check
```

O gerador sem `--caso` e o avaliador sem `--caso` usam todos os casos da T-243/T-245.
A pasta `.avaliacao-t247-t248` é temporária: **não incluir fontes geradas nem respostas do
modelo no PR**. Após rodar, transcrever `prompt_id`, `desfecho` e `passou` dos arquivos JSON
acima para a tabela, junto do identificador do modelo efetivamente usado. Se houver falha
persistente após ajustes, registrar a decisão de escopo no épico E12 antes do encerramento.

## Verificações locais nesta entrega

| Verificação | Resultado |
| --- | --- |
| Compilação sintática dos arquivos Python modificados (`python -m py_compile`) | Aprovada |
| Comparação byte a byte do prompt original com o novo nos nove casos | 6 prompts sem os construtos permaneceram idênticos; só `bonus-fixo-lista-e-filtro`, `janela-datas-black-friday` e `combinado-elementos` mudaram |
| Testes de mutação (retirada temporária da inclusão de instruções) | Os 2 testes específicos falharam corretamente; alteração restaurada e suíte novamente aprovada |
| `pytest tests/app/prompts/test_geracao_codigo.py -k 'not runtime_funciona_fora_do_monorepo'` | 54 aprovados; 1 não selecionado, com adaptador local temporário para `simplejson` |
| Validação do `regrafn.md` contra o oráculo/README do harness, dentro da suíte acima | Aprovada nas verificações locais |
| Teste de runtime isolado do monorepo | Não validado: `simplejson` não instalado no ambiente isolado |
| `worker/tests/scripts/test_casos_geracao.py` | Não coletado: biblioteca `docker` ausente |
| `make pre-commit` (`ruff`, `mypy`, `pytest`) | Não executado: Poetry e dependências não disponíveis |
| Três gerações por caso com Gemini real | **Não executadas: chave ausente** |
| Avaliador no sandbox do worker | **Não executado: Docker ausente** |

**Limitação já registrada no caso da T-245:** no dataset do caso
`janela-datas-black-friday`, `data_ref` é igual a `data_venda` nas vendas datadas.
Consequentemente, esse caso isolado não detecta a implementação incorreta que usa
`data_ref` como substituto; a orientação explícita no prompt e o teste estrutural
reduzem o risco, mas não substituem um caso de regressão que diferencie as colunas.

**Estado final:** mudança pronta para rodadas reais; T-247 e T-248 ainda não concluídas.
