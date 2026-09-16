# Contrato entre o harness e o código gerado

Este documento é a fonte única do contrato da tarefa T-034. As três partes o
referenciam em vez de copiar: o `worker`, que implementa o harness (T-033, T-064),
o `codegen`, que gera código escrito contra ele (T-055), e o próprio código gerado.

Complementa o `docs/ARCHITECTURE.md` §1.4, §1.5 e §3.4, e registra a decisão
[`DEC-091`](../../docs/decisoes/dec-091.md).

## O modelo: harness + submissão

O sandbox roda duas coisas juntas: o harness, que é nosso, e a função gerada pelo
agente. É o modelo de uma maratona de programação: o juiz prepara a entrada, chama a
submissão e confere a saída, e o competidor escreve só a função.

| Maratona | Aqui |
| --- | --- |
| harness | código nosso |
| entrada fixa do problema | os DataFrames já carregados e tipados |
| submissão do competidor | a função gerada pelo agente |
| casos de teste | as asserções invariantes (T-031) |
| veredito AC/WA/RE/TLE | veredito e classificação de falha (T-066, T-065) |

A função gerada é pura: DataFrames entram, resultado sai. Ela não abre arquivo, não
escolhe caminho e não importa nada além do que o harness já importou. Assim ela não
tropeça onde a LLM costuma errar em silêncio (esquecer `dtype=` e virar `matricula`
inteiro, ou deduzir a competência de uma data ambígua), e a reexecução para auditoria
fica simples: mesma entrada, mesmo código, mesmo número.

O modelo não dá isolamento: a função gerada e o harness rodam no mesmo processo
Python. A contenção vem das flags do container (T-064), não do contrato. Por isso o
`apuracao_base` que sai no resultado é reconferido pelo worker, fora do container
(T-066).

## A assinatura

Arquivo único, função única:

```python
# regra.py
def aplicar_regra(bases, apuracao_base, competencia): ...
```

| Parâmetro | Tipo | Descrição |
| --- | --- | --- |
| `bases` | `dict[str, pandas.DataFrame]` | As tabelas da competência: `rh`, `vendas`, `comissoes`, `eventos_rh`. Cópias, já tipadas. |
| `apuracao_base` | `pandas.DataFrame` | O baseline congelado da competência (T-032), carregado como as demais tabelas. |
| `competencia` | `str` | A competência a processar, no formato `AAAA-MM` (ex.: `"2025-11"`). |

Retorno: `dict[str, pandas.DataFrame]` com duas chaves:

| Chave | Conteúdo |
| --- | --- |
| `apuracao_simulada` | Apuração por matrícula sob a regra proposta: `matricula`, `cod_loja`, `cod_marca`, `cod_cargo`, `competencia`, `comissao`. |
| `contribuicoes` | Contribuição por matrícula e por elemento da regra: as mesmas dimensões, mais `elemento_ref` e `delta` (o quanto aquele elemento mudou na comissão da matrícula). |

O harness agrega esse retorno por linha nas dimensões do domínio. A função gerada não
devolve totais nem quebras já somadas.

### Regras da entrada

- **Cópias.** O harness passa cópias dos DataFrames. Uma função que fizer
  `inplace=True` altera só a própria cópia, não o que o harness vê. Verificado em
  `testar-contrato.py`.
- **Sem caminho de arquivo.** Nenhum caminho é passado à função; tudo que ela precisa
  já chega como DataFrame.
- **Competência por parâmetro.** A função recebe a competência e não a deduz de
  `data_ref`, que tem semântica dupla (T-027).
- **Orçamento fica fora.** O orçamento não é parâmetro da função. Ele é o que julga o
  resultado, e quem produz o número não deve alcançar o parâmetro que vai julgá-lo
  (mesmo princípio do T-066).

### Convenção de tipos das colunas

As colunas seguem o dataset canônico (`worker/sandbox/data/domrock/schema.json`).
Atenção a um ponto: no dataset os códigos são inteiros, mas na representação da regra
e nas chaves da decomposição eles são strings (`comum.schema.json`). O código gerado
compara usando o tipo do DataFrame; ao montar as chaves da decomposição, o harness
converte para string.

| Tabela | Colunas (tipo) |
| --- | --- |
| `rh` | `competencia` str, `data_ref` str, `cod_marca` int, `cod_loja` int, `matricula` str, `data_admiss` str, `data_demiss` str\|nulo, `cod_cargo` int, descrições str |
| `vendas` | `competencia` str, `data_ref` str, `data_venda` str\|nulo, `cod_marca` int, `cod_loja` int, `matricula` str, `vlr_venda` float |
| `comissoes` | `competencia` str, `cod_marca` int, `cod_cargo` int, `percentual_comissao` float (fração; `0.025` são 2,5%) |
| `eventos_rh` | tabela congelada de eventos de RH (T-028) |
| `apuracao_base` | `matricula` str, `cod_loja` int, `cod_marca` int, `cod_cargo` int, `competencia` str, `comissao` float |

## O que o harness faz antes e depois

Antes de chamar: carrega as bases e o baseline com tipos explícitos e passa cópias à
função gerada.

Depois de chamar:
1. Agrega `apuracao_simulada` e `apuracao_base` em `totais`.
2. Monta a `decomposicao` por elemento (de `contribuicoes`) e pelas dimensões `loja`,
   `marca`, `cargo` e `competencia`.
3. Roda as asserções invariantes (T-031).
4. Valida a saída contra o schema (`validar-saida.py`).
5. Serializa o resultado.

A decomposição completa (T-035) e as asserções (T-031) são de outras tarefas. O
`harness.py` deste diretório traz uma versão mínima só para os testes do contrato.

## A saída e sua fronteira

O artefato final é o `resultado-simulacao`, descrito por
[`../domain/resultado-simulacao.schema.json`](../domain/resultado-simulacao.schema.json):
`totais`, `assercoes` e `decomposicao`. É contra esse schema que o `validar-saida.py`
confere. Um total sozinho não basta: sem a decomposição não dá para dizer de onde veio
a diferença nem conferir que todo elemento teve efeito.

Fronteira container e worker: o que sai do container não inclui o orçamento nem o
veredito. O harness produz `baseline`, `simulado`, `diferenca_abs`, `diferenca_pct`, a
`decomposicao` e as `assercoes`. É o worker, fora do container, que adiciona o
orçamento a `totais` e calcula o veredito (T-066). O artefato validado neste diretório
já traz o orçamento só para servir de exemplo completo.

## Como o código declara o elemento que implementa

Cada parte da regra tem um identificador estável no espaço único de
`comum.schema.json#/$defs/elemento_ref`: campo do núcleo é `nucleo.<campo>` (ex.:
`nucleo.percentual`), item de `especificacoes` é `elem.<n>` (ex.: `elem.1`).

O código gerado declara o que cada trecho implementa preenchendo `elemento_ref` em
`contribuicoes`, e esses mesmos identificadores viram as chaves de
`decomposicao.elemento`. É essa correspondência que permite conferir a cobertura
(T-056): elemento da representação sem chave na decomposição é erro de geração, e o
job falha em vez de devolver um número que parece completo.

## Bibliotecas permitidas no sandbox

A lista é curta porque cada biblioteca é superfície de ataque num container feito para
rodar código não confiável.

| Biblioteca | Justificativa |
| --- | --- |
| `pandas` | O contrato é baseado em DataFrame; é o que a função gerada usa para apurar. |
| Biblioteca padrão do Python | Operações básicas (datas, matemática, coleções). |

Qualquer biblioteca além dessas precisa de justificativa e de revisão de segurança do
worker antes de entrar na imagem (T-033).

## Suposições em aberto (para revisão no PR)

Ficam registradas aqui em vez de decididas em silêncio (ver também `DEC-091`):

1. **Granularidade do retorno.** A função gerada devolve a apuração por matrícula com
   a atribuição por elemento, e o harness agrega. A alternativa seria a função já
   devolver valores agregados; ficou no harness para não pedir aritmética de totais ao
   código gerado.
2. **Vocabulário da saída.** O critério de aceitação fala em `apuracao_base` e
   `apuracao_simulada`; o schema atual usa `totais.baseline` e `totais.simulado`. Este
   contrato trata os dois como o mesmo par (`apuracao_base` = `totais.baseline`,
   `apuracao_simulada` = `totais.simulado`, ambos agregados). Se o time preferir outro
   nome, é mudança aditiva no schema.

## Como validar e testar

Dependências: `jsonschema` (em `../requirements.txt`) e `pandas` (em `requirements.txt`).

```bash
py -3.12 -m pip install -r contracts/requirements.txt -r contracts/harness/requirements.txt
py -3.12 contracts/harness/testar-contrato.py
py -3.12 contracts/harness/validar-saida.py contracts/examples/domain/resultado-simulacao.json
```

Na CI, esses passos rodam no workflow `Validar contratos`
(`.github/workflows/validar-contratos.yml`).

## Referências

- Issue [#35](https://github.com/Titus-System/synapse/issues/35): T-034.
- `docs/ARCHITECTURE.md` §1.4, §1.5, §3.4.
- `docs/adrs/ADR-002.md`: contratos na raiz, evolução aditiva.
- `../domain/resultado-simulacao.schema.json`, `../domain/representacao-regra.schema.json`.
- `docs/decisoes/dec-091.md`.
