# Contrato entre o harness e o código gerado

Este documento é a fonte única do contrato da tarefa T-034. As três partes o
referenciam em vez de copiar: o `worker`, que implementa o harness (T-033, T-064),
o `codegen`, que gera código escrito contra ele (T-054, T-055), e o próprio código
gerado.

Complementa o `docs/ARCHITECTURE.md` §1.4, §1.5 e §3.4, e registra a decisão
[`DEC-092`](../../docs/decisoes/dec-092.md).

**Se você está escrevendo o prompt de geração de código (T-054):** a seção
["`RegraFn`: o contrato de entrada e saída"](#regrafn-o-contrato-de-entrada-e-saída)
é feita para ser citada quase verbatim - é o que o agente precisa saber para gerar
`regra.py`.

## O modelo: harness + submissão

O sandbox roda duas coisas juntas: o harness, que é nosso, e a função gerada pelo
agente. É o modelo de uma maratona de programação: o juiz prepara a entrada, chama a
submissão e confere a saída, e o competidor escreve só a função.

| Maratona | Aqui |
| --- | --- |
| harness | código nosso |
| entrada fixa do problema | os DataFrames já carregados e tipados |
| submissão do competidor | a função gerada pelo agente (`RegraFn`) |
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

## Uma execução, um período de competências

**Um job pode cobrir mais de um mês** - por exemplo, uma regra sazonal testada contra
setembro, outubro e novembro juntos. Isso já é assim em todo o resto do sistema:
`jobs.competencias` e `contracts/events/executar-codigo.schema.json#/properties/competencias`
são array desde antes deste contrato. **Este harness processa o período inteiro numa
única chamada da função gerada - nunca um container por mês.** É por isso que o
terceiro parâmetro de `aplicar_regra` é `competencias: list[str]`, não `competencia: str`.

Os totais (`resultado-totais`) são do período inteiro; a contribuição de cada mês sai
separada em `decomposicao.competencia` - esse schema já previa a quebra mensal, e não
muda com esta decisão.

## A assinatura

Arquivo único, função única:

```python
# regra.py
def aplicar_regra(bases, apuracao_base, competencias): ...
```

| Parâmetro | Tipo | Descrição |
| --- | --- | --- |
| `bases` | `dict[str, pandas.DataFrame]` | As tabelas do período: `rh`, `vendas`, `comissoes`, `eventos_rh`. Cópias, já tipadas. |
| `apuracao_base` | `pandas.DataFrame` | O baseline congelado (T-032) das competências do período, concatenado. |
| `competencias` | `list[str]` | As competências a processar, cada uma `AAAA-MM` (ex.: `["2025-09", "2025-10", "2025-11"]`), na ordem crescente em que chegaram no comando `executar-codigo`. |

Retorno: `dict[str, pandas.DataFrame]` com duas chaves:

| Chave | Conteúdo |
| --- | --- |
| `apuracao_simulada` | Apuração por matrícula e por competência sob a regra proposta: `matricula`, `cod_loja`, `cod_marca`, `cod_cargo`, `competencia`, `comissao`. Mesmo formato de `apuracao_base`, com o mesmo conjunto de linhas (uma por matrícula elegível e por competência do período) - a regra ajusta `comissao` onde se aplica e mantém as demais linhas iguais ao baseline. |
| `contribuicoes` | Contribuição por matrícula, por competência e por elemento da regra: as mesmas dimensões de `apuracao_simulada`, mais `elemento_ref` e `delta` (o quanto aquele elemento mudou a comissão daquela matrícula naquela competência). |

O harness agrega esse retorno por linha nas dimensões do domínio, inclusive por
competência. A função gerada não devolve totais nem quebras já somadas.

## `RegraFn`: o contrato de entrada e saída

Esta seção descreve `RegraFn` - o tipo da função que o código gerado precisa
implementar - com detalhe suficiente para ser a única referência que o agente de
geração (T-054/T-055) recebe sobre o formato esperado.

```python
type RegraFn = Callable[
    [dict[str, pandas.DataFrame], pandas.DataFrame, list[str]],
    dict[str, pandas.DataFrame],
]
```

### O que a função recebe

**`bases: dict[str, pandas.DataFrame]`** - exatamente quatro chaves, sempre presentes:
`"rh"`, `"vendas"`, `"comissoes"`, `"eventos_rh"`. Cada valor é uma cópia independente
(seção "Regras da entrada" abaixo) já tipada conforme a tabela de "Convenção de tipos
das colunas". Duas tabelas se comportam de modo diferente quanto ao recorte temporal:

| Tabela | Cobertura |
| --- | --- |
| `rh`, `vendas`, `comissoes` | Só as linhas cujas `competencia` estão em `competencias` - o período do job, nunca mais. |
| `eventos_rh` | **Todo o histórico congelado (T-028/T-029), sem filtro.** Um evento de competência anterior (ex.: correção cadastral, afastamento em curso) pode afetar um mês do período mesmo tendo `competencia_origem` fora dele. |

Cada tabela tem sua própria coluna `competencia` (exceto `eventos_rh`, que usa
`competencia_origem`, `data_inicio` e `data_fim` - ver a tabela de tipos). A função
gerada nunca recebe uma tabela pré-filtrada para uma competência só, mesmo num job de
um mês: o formato é sempre "zero ou mais linhas por competência processada", e a
própria função decide o que fazer com cada uma. Isso é o que permite a uma regra
sazonal (ex.: Black Friday, só em novembro) processar um período de três meses sem
efeito nos outros dois.

**`apuracao_base: pandas.DataFrame`** - o baseline congelado (T-032), concatenado para
todas as competências de `competencias`: uma linha por matrícula elegível e por
competência, com `matricula`, `cod_loja`, `cod_marca`, `cod_cargo`, `competencia`,
`comissao`. É o ponto de partida do cálculo - a maioria das regras gera
`apuracao_simulada` copiando `apuracao_base` e ajustando `comissao` só onde a regra se
aplica.

**`competencias: list[str]`** - as mesmas competências que recortam `bases`, na forma
`AAAA-MM`, em ordem crescente. É como a função sabe qual período está processando sem
depreender de `data_ref` (que tem semântica dupla - seção "Regras da entrada").
**Os parâmetros específicos da regra proposta (percentual, marca, cargo, vigência,
faixas, exclusões etc.) não chegam por aqui.** Eles são traduzidos para o corpo do
código gerado como constantes/lógica Python - exatamente como no exemplo
(`contracts/harness/exemplo/regra.py`), onde `_MARCA_ALVO`, `_CARGO_ALVO` e
`_PERCENTUAL` são valores fixos escritos pelo agente, não parâmetros da função. Uma
regra com vigência de só um dos meses do período decide isso internamente, comparando
a `competencia` de cada linha com o que a regra propõe (ex.: `if competencia ==
"2025-11":`).

### O que a função devolve

Um `dict` com exatamente as duas chaves descritas na tabela da seção "A assinatura":
`apuracao_simulada` e `contribuicoes`. Nenhuma chave extra é lida pelo harness; nenhuma
das duas pode faltar.

**`apuracao_simulada`** - mesmo formato de `apuracao_base` (mesmas colunas e tipos).
Precisa ter **o mesmo conjunto de linhas** de `apuracao_base` (mesma `matricula` +
`competencia` em ambas) - a regra não cria matrícula nem competência que não estava no
baseline, e não remove nenhuma. Uma linha sem efeito da regra tem o mesmo valor de
`comissao` que tinha em `apuracao_base`.

**`contribuicoes`** - uma linha por combinação de `matricula`, `competencia` e
`elemento_ref` **que a regra efetivamente afetou** (`delta != 0`); linhas sem efeito
não entram aqui - o exemplo já filtra assim
(`contribuicoes[contribuicoes["delta"] != 0.0]`). Colunas: `matricula`, `cod_loja`,
`cod_marca`, `cod_cargo`, `competencia`, `elemento_ref`, `delta`. `elemento_ref` é o
identificador do elemento da representação que produziu aquele delta (seção "Como o
código declara o elemento que implementa"); `delta` é
`apuracao_simulada.comissao − apuracao_base.comissao` para aquela matrícula e
competência, atribuído ao elemento responsável. Quando mais de um elemento afeta a
mesma matrícula na mesma competência (ex.: um acréscimo percentual e uma exclusão
concorrendo), cada elemento entra com sua própria linha e seu próprio `delta` - a soma
das linhas daquela matrícula/competência em `contribuicoes` bate com a diferença total
dela entre `apuracao_simulada` e `apuracao_base`.

### O que "pura" significa aqui

- **Sem I/O.** Não abre arquivo, não faz requisição de rede (o container não tem rede
  de qualquer forma - T-064), não lê variável de ambiente, não escreve em disco fora do
  que o harness pedir.
- **Sem import além do permitido.** Só `pandas` e a biblioteca padrão do Python
  (seção "Bibliotecas permitidas no sandbox"). Nenhum outro pacote está instalado na
  imagem, então um import além desses falha com `ImportError`, não com violação de
  sandbox.
- **Sem estado entre chamadas.** Cada execução é um processo novo; não há cache,
  variável de módulo mutável entre execuções, nem arquivo temporário reaproveitado.
- **Determinística.** As mesmas entradas produzem sempre a mesma saída - sem
  `datetime.now()`, `random` sem seed fixa, nem iteração sobre `dict`/`set` cuja ordem
  o resultado dependa de forma observável.
- **Não muta as entradas.** Ver "Regras da entrada" - o harness já garante isso
  passando cópias, mas a função não deve depender de conseguir alterar o que recebeu.

### O que acontece quando a função falha

A função pode levantar qualquer exceção Python (ex.: `KeyError` por coluna ausente,
`ZeroDivisionError`). O harness não a captura silenciosamente: uma exceção não tratada
propaga e o worker classifica a execução como `erro_codigo` (T-065) - o job para, não
devolve número parcial. O mesmo vale para um retorno que não seja um `dict` com as
duas chaves esperadas, ou cujos DataFrames não tenham as colunas exigidas: o validador
de saída (`validar-saida.py`) rejeita antes de o resultado ser aceito, e essa rejeição
também vira `erro_codigo`. Não existe "resultado parcial aceito" - ver ARCHITECTURE.md
§1.5, "a regra é simulada por inteiro".

### Exemplo mínimo, com duas competências

```python
def aplicar_regra(bases, apuracao_base, competencias):
    vendas = bases["vendas"]
    vendas_periodo = vendas[vendas["competencia"].isin(competencias)]
    vendas_por_matricula_competencia = vendas_periodo.groupby(
        ["matricula", "competencia"], as_index=False
    )["vlr_venda"].sum()

    # merge, não .map() por tupla: mais legível e preserva a ordem das linhas
    # de apuracao_base sem exigir index composto.
    simulada = apuracao_base.merge(
        vendas_por_matricula_competencia, on=["matricula", "competencia"], how="left"
    )
    simulada["vlr_venda"] = simulada["vlr_venda"].fillna(0.0)
    no_alvo = (simulada["cod_marca"] == 10) & (simulada["competencia"] == "2025-11")

    nova_comissao = simulada["comissao"].where(~no_alvo, simulada["vlr_venda"] * 0.01)
    delta = nova_comissao - simulada["comissao"]
    simulada["comissao"] = nova_comissao
    simulada = simulada.drop(columns="vlr_venda")

    contribuicoes = apuracao_base[
        ["matricula", "cod_loja", "cod_marca", "cod_cargo", "competencia"]
    ].copy()
    contribuicoes["elemento_ref"] = "elem.1"
    contribuicoes["delta"] = delta.to_numpy()
    contribuicoes = contribuicoes[contribuicoes["delta"] != 0.0].reset_index(drop=True)

    return {"apuracao_simulada": simulada.reset_index(drop=True), "contribuicoes": contribuicoes}
```

Chamado com `competencias=["2025-09", "2025-10", "2025-11"]`, esse exemplo (acréscimo
de 1% em novembro na marca 10) devolve `apuracao_simulada` com linhas para os três
meses, mas só altera `comissao` nas linhas de novembro/marca 10; `contribuicoes` só
tem linhas de novembro. Setembro e outubro aparecem em `decomposicao.competencia` com
valor zero - simulados e sem efeito, não ausentes (ver `resultado-decomposicao.schema.json`).
O exemplo completo, testado e validado, está em
[`exemplo/regra.py`](exemplo/regra.py).

## O harness: `preparar()`, `chamar()`, `montar_resultado()`

O harness de referência usado nos testes deste contrato está em
[`exemplo/harness.py`](exemplo/harness.py). A implementação de produção é do `worker`
(T-033, T-064, T-066); esta é a versão mínima que prova o contrato.

### `preparar(bases) -> dict[str, pandas.DataFrame]`

```python
def preparar(bases: dict[str, pandas.DataFrame]) -> dict[str, pandas.DataFrame]:
```

Devolve uma cópia profunda (`.copy(deep=True)`) de cada DataFrame em `bases`. Existe
para isolar as tabelas que o harness carregou das que a função gerada recebe - é o que
sustenta a garantia de "Regras da entrada" abaixo. Não filtra, não transforma: o
recorte por `competencias` já aconteceu antes, na preparação real (T-033), fora do
escopo deste contrato mínimo.

### `chamar(regra, bases, apuracao_base, competencias) -> dict[str, pandas.DataFrame]`

```python
def chamar(
    regra: RegraFn,
    bases: dict[str, pandas.DataFrame],
    apuracao_base: pandas.DataFrame,
    competencias: list[str],
) -> dict[str, pandas.DataFrame]:
```

Chama `regra` (a função gerada) passando cópias de `bases` (via `preparar`) e de
`apuracao_base`, mais `competencias` como veio. É a única função que efetivamente
invoca o código gerado - tudo antes dela é preparação, tudo depois dela é agregação.
Existe separada de `montar_resultado` porque as duas têm falhas diferentes: uma
exceção aqui dentro é `erro_codigo` (a função gerada quebrou); uma falha em
`montar_resultado` é bug do harness, não do código gerado.

### `montar_resultado(saida, apuracao_base, competencias, orcamento) -> dict`

```python
def montar_resultado(
    saida: dict[str, pandas.DataFrame],
    apuracao_base: pandas.DataFrame,
    competencias: list[str],
    orcamento: float,
) -> dict[str, Any]:
```

Agrega o retorno de `regra` (`saida`) no formato de `resultado-simulacao`: soma
`apuracao_base.comissao` e `apuracao_simulada.comissao` em `totais.baseline` e
`totais.simulado`; agrupa `contribuicoes` por `elemento_ref` para `decomposicao.elemento`
e por `cod_loja`/`cod_marca`/`cod_cargo`/`competencia` para as demais quebras - **uma
entrada por competência de `competencias`, mesmo quando o delta daquele mês é zero**
(ver "Uma execução, um período de competências"). `orcamento` entra aqui só para o
exemplo ficar completo; em produção quem aplica o critério de orçamento é o `worker`,
fora do container (T-066) - `montar_resultado` não decide viabilidade, só agrega.

## Regras da entrada

- **Cópias.** O harness passa cópias dos DataFrames. Uma função que fizer
  `inplace=True` altera só a própria cópia, não o que o harness vê. Verificado em
  `testar-contrato.py`.
- **Sem caminho de arquivo.** Nenhum caminho é passado à função; tudo que ela precisa
  já chega como DataFrame.
- **Competências por parâmetro.** A função recebe a lista de competências e não a
  deduz de `data_ref`, que tem semântica dupla (T-027): a maioria das linhas traz o
  dia 1º do mês, mas as vendas de 24 a 28/11 trazem a data real da venda.
- **Orçamento fica fora.** O orçamento não é parâmetro da função. Ele é o que julga o
  resultado, e quem produz o número não deve alcançar o parâmetro que vai julgá-lo
  (mesmo princípio do T-066).

## Convenção de tipos das colunas

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
| `eventos_rh` | `id` str, `tipo` str (`afastamento` \| `ferias` \| `licenca_maternidade` \| `demissao` \| `correcao_cadastral`), `matricula` str, `competencia_origem` str, `data_inicio` str, `data_fim` str\|nulo, `detalhes` objeto\|nulo. Não filtrada por `competencias` - ver "O que a função recebe". |
| `apuracao_base` | `matricula` str, `cod_loja` int, `cod_marca` int, `cod_cargo` int, `competencia` str, `comissao` float |

`data_fim` em `eventos_rh` pode ser nulo mesmo quando o evento tem duração conhecida
(licença-maternidade sem retorno registrado usa `detalhes.data_fim_estimada` - ver
`worker/app/sandbox/regras_base.py`, que já trata esse caso na apuração base e serve
de referência de leitura, embora essa lógica não seja reaproveitada pelo código
gerado).

## O que o harness faz antes e depois

Antes de chamar: carrega as bases e o baseline com tipos explícitos, recorta pelas
competências do job (exceto `eventos_rh` - histórico completo) e passa cópias à
função gerada.

Depois de chamar:
1. Agrega `apuracao_simulada` e `apuracao_base` em `totais`, somando o período inteiro.
2. Monta a `decomposicao` por elemento (de `contribuicoes`) e pelas dimensões `loja`,
   `marca`, `cargo` e `competencia` - uma entrada por mês do período, mesmo com zero.
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
| `pandas` (`>=2.2,<3.0`) | O contrato é baseado em DataFrame; é o que a função gerada usa para apurar. Trancado na major `2.x` porque é a API mais representada no material de treino dos modelos disponíveis hoje - `pandas 3.x` muda o dtype textual padrão e liga copy-on-write por padrão, o que produziria código plausível e sutilmente errado. |
| Biblioteca padrão do Python | Operações básicas (datas, matemática, coleções). |

Qualquer biblioteca além dessas precisa de justificativa e de revisão de segurança do
worker antes de entrar na imagem (T-033).

## Suposições em aberto (para revisão no PR)

Ficam registradas aqui em vez de decididas em silêncio (ver também `DEC-092`):

1. **Granularidade do retorno.** A função gerada devolve a apuração por matrícula e
   competência com a atribuição por elemento, e o harness agrega. A alternativa seria a
   função já devolver valores agregados; ficou no harness para não pedir aritmética de
   totais ao código gerado.
2. **Vocabulário da saída.** O critério de aceitação fala em `apuracao_base` e
   `apuracao_simulada`; o schema atual usa `totais.baseline` e `totais.simulado`. Este
   contrato trata os dois como o mesmo par (`apuracao_base` = `totais.baseline`,
   `apuracao_simulada` = `totais.simulado`, ambos agregados sobre o período inteiro).
   Se o time preferir outro nome, é mudança aditiva no schema.
3. **Filtro de `bases` por competência.** A decisão de filtrar `rh`/`vendas`/`comissoes`
   ao período do job mas deixar `eventos_rh` inteira (seção "O que a função recebe") é
   inferida da forma como T-030 já trata `eventos_rh` internamente, não de um requisito
   escrito em nenhuma issue. Se o time preferir passar as cinco competências completas
   em toda execução (mais simples de implementar em T-033, mais dado exposto ao código
   gerado), é mudança só na preparação do harness - a assinatura de `aplicar_regra` não
   muda.

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
- `../events/executar-codigo.schema.json`: origem de `competencias` como array.
- `docs/decisoes/dec-092.md`.
