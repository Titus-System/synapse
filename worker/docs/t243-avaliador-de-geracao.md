# T-243: avaliador de código gerado e casos de referência

A asserção e a conferência de cobertura mostram que o código gerado rodou e declarou o que
implementou, mas não que ele **calculou certo**. Esta entrega cria os casos com resultado
esperado e o avaliador que roda um `regra.py` qualquer no sandbox e o compara com eles. É com ele
que o codegen ajusta o prompt (T-244, T-246 a T-250).

O avaliador é ferramenta de desenvolvimento, e não um fluxo da aplicação: não publica evento, não
grava em banco e não tem métrica.

## Onde está

| Arquivo | O quê |
| --- | --- |
| `scripts/casos_geracao.py` | o formato do caso, `executar_caso` (a execução compartilhada) e `comparar` |
| `scripts/gravar_esperado.py` | roda a referência de cada caso e grava `esperado.json` |
| `scripts/avaliar_geracao.py` | roda um código gerado por caso e dá o relatório |
| `tests/fixtures/casos_geracao/<id>/` | os casos |
| `tests/scripts/test_casos_geracao.py` | formato, recusas e comparação, sem Docker |
| `tests/scripts/test_avaliar_geracao_integration.py` | referências e avaliador contra a imagem real (`docker`) |

## O formato de um caso

Uma pasta por caso, com o `id` como nome:

| Arquivo | Conteúdo |
| --- | --- |
| `caso.json` | `id`, `descricao` (o que o caso prova), `leitura` (a interpretação da regra que a referência implementa, com as premissas que mudam o número), `representacao` e `competencias` |
| `referencia.py` | a implementação de referência, escrita à mão contra o contrato `RegraFn` (`contracts/harness/README.md`) |
| `esperado.json` | o que a referência produz no sandbox, gravado pelo script e **nunca escrito à mão** |

Ao carregar, `representacao` é validada contra `contracts/domain/representacao-regra.schema.json`,
e `competencias` precisa vir como o comando a mandaria: não vazia, crescente, sem repetição e só
com competências que o dataset publica. Campo a mais ou a menos é recusado.

`esperado.json` guarda só agregados. Num sucesso, `totais` e a quebra por elemento
(`decomposicao.elemento`); numa falha, `classe`, `motivo` e `tipo_erro`. Ele traz também as
`competencias` com que foi gravado, e um esperado de outro período é recusado.

## Os casos

| Caso | Regra | Período | Esperado |
| --- | --- | --- | --- |
| `nucleo-controle` | só núcleo, a do exemplo do harness: 2,5% das vendas para marca 10 e cargo 100 | `2025-08` e `2025-11` (meses não seguidos) | `nucleo.percentual` -23.740,16 |
| `generico-admissao` | núcleo + `elem.1` (`generico`): mais 1 p.p. para quem, dentro do recorte do núcleo, foi admitido antes de 01/01/2020 (`data_admiss`) | as cinco competências (o padrão) | `elem.1` 34.770,95; `nucleo.percentual` -805.757,82 |
| `generico-aniversario-loja` | a representação de `contracts/examples/domain/representacao-regra-generico.json`: dobrar a comissão no aniversário da loja, data que nenhuma base tem | `2025-11` (um mês só) | falha: `erro_codigo`, `excecao`, `NotImplementedError` |

Os três períodos cobrem os formatos que um job pode pedir (ARCHITECTURE.md §1.3): o período inteiro,
um subconjunto não contíguo e um mês só. No recorte do `generico-admissao`, de 34 a 36 pessoas por
mês foram admitidas antes do corte, de cerca de 340.

A referência do caso impossível levanta `NotImplementedError("elem.1: ...")`, como o contrato do
harness manda. Declarar `elem.1` com efeito zero devolveria um número que parece completo sem a
parte da regra que faltou.

## Uso

Na pasta `worker`, com o Docker de pé e a imagem do sandbox construída
(`docker build -f worker/sandbox/Dockerfile -t synapse-sandbox:local .`, na raiz do monorepo):

```bash
# grava o esperado de todos os casos (ou de um, com --caso ID; --caso pode repetir)
poetry run python -m scripts.gravar_esperado
# confere, sem escrever, que as referências ainda reproduzem o esperado gravado
poetry run python -m scripts.gravar_esperado --check
# avalia uma pasta com um <id>.py por caso
poetry run python -m scripts.avaliar_geracao --codigo /caminho/da/pasta
poetry run python -m scripts.avaliar_geracao --codigo /caminho/da/pasta --caso generico-admissao --json
```

`--imagem TAG` troca a imagem; o padrão é `SANDBOX_IMAGE` (`synapse-sandbox:local`). Antes de
gravar um esperado novo, revise os números: o esperado é o que a referência calcula, e uma
referência errada grava um esperado errado.

O avaliador procura `<pasta>/<id>.py` para cada caso pedido e sai com:

| Código | Quando |
| --- | --- |
| 0 | todos os casos passaram (`bate` ou `falhou_como_esperado`) |
| 1 | algum caso não passou (`diverge` ou `falhou_sem_esperar`) |
| 2 | erro de uso ou de infraestrutura: caso inexistente, arquivo faltando, esperado ausente, daemon ou imagem indisponível |

Exemplo do relatório em texto, com o `elem.1` de `generico-admissao` trocado de 1% para 2%:

```text
generico-admissao: diverge
  total simulado: esperado 2528907.37, obtido 2563678.45 (tolerância 26.72)
  elem.1: esperado 34770.95, obtido 69542.14
0 de 1 casos passaram
```

`--json` dá o mesmo por caso: `desfecho`, `passou`, `classe`, `motivo`, os totais simulados, a
`tolerancia` e as `diferencas` por elemento.

## Os quatro desfechos

| Esperado | Obtido | Desfecho |
| --- | --- | --- |
| número | total e cada elemento dentro da tolerância | `bate` |
| número | total ou algum elemento fora da tolerância | `diverge` |
| número | qualquer falha | `falhou_sem_esperar` |
| falha | `erro_codigo`, `excecao`, `NotImplementedError` | `falhou_como_esperado` |
| falha | um número | `diverge`: a regra foi simulada pela metade |
| falha | qualquer outra falha (`KeyError`, timeout, saída fora do contrato) | `falhou_sem_esperar` |

A falha esperada exige o tipo `NotImplementedError`: um `KeyError` ou um timeout também param o
job, mas não provam que a geração reconheceu o elemento impossível. O tipo vindo do código gerado
é comparado e nunca aparece no relatório.

Elemento sem chave em `decomposicao.elemento` vale zero, porque a decomposição só tem chave para
elemento com contribuição.

## A tolerância: um centavo por linha do período

O harness arredonda a comissão de cada linha (matrícula e competência) a centavos e confere a
atribuição de cada linha com tolerância de um centavo. Duas fórmulas equivalentes podem
arredondar para lados opostos uma linha que cai exatamente em meio centavo, e no recorte do núcleo
são 138 das 1.695 linhas a 2,5%. Medido contra o caso de controle, com tolerância de um centavo
no total:

| Variação da referência | Diferença |
| --- | --- |
| `venda * 2.5 / 100` | +0,03 no total |
| `venda / 40` | -0,02 no total |
| `generico-admissao` somando as parcelas (`venda * 0.025 + venda * 0.01`) | +0,02 em `elem.1`, -0,02 no núcleo |

Todas reprovariam um código correto. Por isso a tolerância é a do harness somada sobre o
período: **um centavo por linha do baseline congelado**, contadas no manifesto (497, 530, 537,
546 e 562 linhas de agosto a dezembro). Ela vale para o total simulado e para cada elemento:
R$ 26,72 nos cinco meses, R$ 10,43 em agosto e novembro, R$ 5,46 só em novembro. Para
comparação, o `elem.1` do `generico-admissao` vale em média R$ 197 por pessoa e mês. Um erro
menor que a tolerância não é detectado.

## Isolamento

O código, de referência ou gerado, só roda no container, pelo caminho da fila:
`executar_no_sandbox`, `classificar` e `julgar`, com o mesmo isolamento e a mesma conferência do
baseline congelado (T-066). Nenhum script importa o código no processo do worker. Do que volta do
container só se usa a classe, o motivo, os totais e as chaves de `decomposicao.elemento`, que o
schema do resultado restringe ao padrão de `elemento_ref`. O relatório não traz linha de
dataset, stdout, stderr nem mensagem de erro do código gerado.

O orçamento não importa, porque não há veredito: os scripts passam `0.0` a `classificar` e
`julgar`, e o veredito que sai deles nunca é lido.

## Para a T-241 e a T-245

- A T-241 vai passar os `elementos_exigidos` de cada caso pelo avaliador; o ponto de extensão é
  `executar_caso`. As referências já declaram `elementos_implementados`.
- A T-245 acrescenta casos com o mesmo formato: uma pasta com `caso.json` e `referencia.py`, e o
  esperado gravado por `scripts.gravar_esperado --caso ID`. A premissa que muda o número e que o
  contrato não define vai em `leitura`.

## Verificação

```bash
sh verify.sh   # inclui tests/scripts/test_avaliar_geracao_integration.py (marcado docker)
poetry run python -m scripts.gravar_esperado --check
```
