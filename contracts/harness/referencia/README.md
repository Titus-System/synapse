# Regra de referência (T-036)

Exemplo determinístico, escrito à mão contra o contrato do harness
([`../README.md`](../README.md), T-034), com resultado conhecido e estável.
Serve de gabarito para dois usos: referência para a geração de código por LLM
(T-054) e valor esperado do teste de ponta a ponta (T-076).

## A regra

Acréscimo de **0,3%** na comissão sobre as vendas da **marca 40**, na competência
de **novembro/2025**, para os cargos de venda — loja (100), balcão (200) e
assistente (300) —, **exceto o gerente** (150). É `adicional_percentual` no
vocabulário das políticas históricas (T-032).

## Os arquivos

| Arquivo | O que é |
| --- | --- |
| `regra.py` | O `aplicar_regra` da regra, no contrato da T-034. |
| `representacao.json` | A representação da regra (`representacao-regra.schema.json`, T-004). |
| `resultado-esperado.json` | A saída do sandbox sobre novembro: `totais`, `assercoes` e `decomposicao`, sem `orcamento` (que o worker acrescenta fora do container, T-066). |

## O resultado

Sobre novembro/2025, com o baseline congelado da T-032 (`508382.32`):

| Total | Valor |
| --- | --- |
| baseline | `508382.32` |
| simulado | `511131.25` |
| diferença | `+2748.93` (`+0,54%`) |

Toda a diferença cai em `nucleo.percentual`, na marca 40 e na competência
2025-11. Na quebra por cargo, ela se concentra no **balcão (200)**: nos dados,
os cargos 100 e 300 não têm vendas de marca 40 em novembro, então saem com zero.

**O número depende do baseline.** Se a T-032 for reapurada, este resultado e a
asserção da T-076 mudam junto.

## Como reproduzir

Da raiz do monorepo, com a imagem construída (`docker build -f
worker/sandbox/Dockerfile -t synapse-sandbox:local .`):

```bash
# o payload leva a fonte da regra e a competência; a imagem devolve o envelope
docker run --rm -i --network none --read-only synapse-sandbox:local < payload.json
```

O teste `worker/tests/app/sandbox/test_regra_referencia.py` (marcado `docker`)
monta esse payload, roda pela imagem e confere a saída contra
`resultado-esperado.json`.
