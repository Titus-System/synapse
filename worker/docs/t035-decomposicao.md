# T-035 — Decomposição do resultado no sandbox

`app/sandbox/resultado.py` agrega o retorno da função gerada no formato de
`contracts/domain/resultado-simulacao.schema.json`. É a etapa que fecha o
harness: a função gerada devolve valores **por matrícula**, este módulo produz
os **agregados** que a tela, a explicação e a auditoria consomem.

Existe porque um total sozinho não permite conferir nada. O nível 2 da
explicabilidade (`docs/ARCHITECTURE.md` §3.3) é o gestor querendo entender o
número, e ele só existe se a saída sair decomposta: quanto cada elemento da
regra e cada dimensão do domínio contribuiu para a diferença em relação ao
baseline. O agente **narra** essa decomposição (T-058, T-060); não a calcula.

```python
montar_resultado(
    saida,            # {"apuracao_simulada": ..., "contribuicoes": ...}, da T-034
    apuracao_base,    # baseline congelado do período (T-032), na forma do contrato
    competencias,     # as competências do job, na ordem recebida
    assercoes=...,    # desfecho das invariantes, pronto da T-031
) -> ResultadoSimulacao
```

Entradas e saídas são tabelas do contrato: `Sequence[Mapping]` ou qualquer
objeto com `.to_dict(orient="records")`. O módulo não importa pandas, não lê
arquivo, não acessa rede e não conhece orçamento.

## As cinco quebras

Toda quebra é da **diferença** em relação ao baseline, nunca do total: somar
qualquer uma delas dá `totais.diferenca_abs`.

| Quebra | Origem | Chave ausente significa |
| --- | --- | --- |
| `elemento` | `contribuicoes`, somadas por `elemento_ref` | efeito não mensurável ou implementação faltante (diagnóstico é da T-056) |
| `loja`, `marca`, `cargo` | delta por linha, com a dimensão do **baseline** | a dimensão não existe no período apurado |
| `competencia` | delta por linha, uma entrada por competência do job | a competência não foi simulada |

**Zero e ausência dizem coisas diferentes, e o zero é preservado.** Elemento cujas
contribuições se cancelam sai com `0.0`; competência simulada sem efeito sai com
`0.0`; loja presente no período e não afetada sai com `0.0`. No dataset atual são
80 lojas, 6 marcas, 4 cargos e até 5 competências: cerca de uma centena de valores
agregados, nunca uma linha das bases.

As dimensões vêm sempre do baseline, não da apuração simulada — assim o código
gerado não consegue mover uma matrícula de loja e distorcer a quebra. Uma
divergência entre as duas é recusada em vez de absorvida, e as colunas de
dimensão de `contribuicoes` são ignoradas de propósito.

## Arredondamento e reconciliação

A comissão é arredondada **uma vez por linha** (`ROUND_HALF_UP`, duas casas),
exatamente como a T-032 faz ao congelar o baseline. Com as parcelas em centavos,
o delta de cada linha é múltiplo exato de centavo e as quebras por loja, marca,
cargo e competência somam a diferença total sem resíduo, por construção.

As contribuições são somadas **sem arredondar** e cada balde de elemento é
arredondado uma vez, no fim. Como a diferença é arredondada por linha e os baldes
por elemento, as duas somas podem ficar a centavos uma da outra; o resíduo é
somado ao balde de maior valor absoluto, com empate pelo menor identificador.
É o único ajuste do módulo, ele é determinístico e existe para a quebra fechar
exatamente com o total exibido.

A conferência da atribuição tolera **um centavo por matrícula e competência**: o
delta vem de pontas arredondadas e o atribuído não, então um centavo é
aritmética, não defeito. Acima disso, o código gerado atribuiu errado.

## Erros

Todos descendem de `ResultadoInvalidoError(ValueError)` e significam defeito do
código gerado — `erro_codigo` para a classificação da T-065, nunca inviabilidade
orçamentária. As mensagens citam no máximo cinco chaves mais a contagem; erro não
é lugar para despejar dataset.

| Situação | Exceção |
| --- | --- |
| tabela ou coluna ausente, valor não numérico ou não finito, código inválido | `ResultadoInvalidoError` |
| linha da simulada ausente, extra ou duplicada; dimensão divergente do baseline; contribuição de linha inexistente | `ResultadoInvalidoError` |
| `elemento_ref` fora de `nucleo.<campo>` / `elem.<n>` | `ResultadoInvalidoError` |
| diferença sem nenhum elemento que a assuma | `DecomposicaoInconsistenteError` |
| elementos que não somam a diferença da linha | `DecomposicaoInconsistenteError` |

Os padrões de `elemento_ref` e de `competencia` são cópias das definições de
`contracts/domain/comum.schema.json`: `contracts/` é insumo de build, nunca
dependência de runtime (ADR-002). Um teste confere que não divergiram.

## Limite desta entrega

`totais` sai **sem `orcamento`**: o container não recebe o critério que vai
julgá-lo, e é o worker, fora do container, que acrescenta o orçamento e calcula o
veredito (T-066). A consequência prática é que a saída deste módulo, sozinha,
**não valida** contra `resultado-simulacao.schema.json` — falta `totais.orcamento`.
A validação só fecha depois do passo do worker, e é assim que o teste a exercita.

Daí também a escolha de não importar `jsonschema` aqui: o contrato do harness
lista a validação entre os passos do sandbox, mas a imagem só admite `pandas` e a
biblioteca padrão. Validar fora do container, na T-065, resolve as duas coisas;
se a T-064 quiser validar dentro, terá de tratar o schema parcial. Fica
registrado como pendência da fiação.

O módulo ainda não tem chamador: quem o liga ao fluxo é o harness de produção
(T-033), que carrega as bases e o baseline e chama a função gerada. T-035 não
sobe container, não lê baseline do disco, não roda invariante (recebe o desfecho
pronto) e não decide viabilidade.

Quando a T-066 reconferir a apuração base fora do container, deve comparar **em
centavos**: aqui as parcelas são quantizadas por linha, e somar float cru do
outro lado produziria diferenças de fração de centavo sem significado.

## Verificação

Na pasta `worker/`:

```bash
poetry run pytest tests/app/sandbox/test_resultado.py
sh verify.sh
```

Os testes cobrem a reconciliação das cinco quebras, o elemento que se cancela, a
competência sem efeito, a diferença zero, o resíduo de arredondamento, cada
recusa da tabela acima, tabela DataFrame-like sem pandas, ordenação determinística
e a validação da saída pelo validador do contrato (`contracts/harness/validar-saida.py`),
executado por subprocesso com o orçamento acrescentado como o worker fará.

A validação pelo schema roda em dez cenários: diferença zero e negativa, elemento que se
cancela, competência sem efeito e sem nenhuma linha, baseline zero, resíduo de
arredondamento, códigos como texto, elementos de núcleo e de especificação, e várias
dimensões em duas competências. Outro teste adultera a saída (sem `orcamento`, sem
`decomposicao`, `elemento_ref` ou competência inválidos, valor não numérico) e exige que o
validador a rejeite, provando que ele não é vacuoso.

O schema valida forma e tipos, não aritmética, e não restringe as chaves de `loja`, `marca`
e `cargo`. A reconciliação das quebras com `totais.diferenca_abs` é conferida pelos testes
próprios, não pelo validador.
