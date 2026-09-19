## A assinatura

Arquivo único, função única:

```python
# regra.py
def aplicar_regra(bases, apuracao_base, competencias): ...
```

| Parâmetro | Tipo | Descrição |
| --- | --- | --- |
| `bases` | `dict[str, pandas.DataFrame]` | As tabelas do período: `rh`, `vendas`, `comissoes`, `eventos_rh`. Cópias, já tipadas. |
| `apuracao_base` | `pandas.DataFrame` | O baseline congelado das competências do período, concatenado. |
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
geração recebe sobre o formato esperado.

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
| `eventos_rh` | **Todo o histórico congelado, sem filtro.** Um evento de competência anterior (ex.: correção cadastral, afastamento em curso) pode afetar um mês do período mesmo tendo `competencia_origem` fora dele. |

Cada tabela tem sua própria coluna `competencia` (exceto `eventos_rh`, que usa
`competencia_origem`, `data_inicio` e `data_fim` - ver a tabela de tipos). A função
gerada nunca recebe uma tabela pré-filtrada para uma competência só, mesmo num job de
um mês: o formato é sempre "zero ou mais linhas por competência processada", e a
própria função decide o que fazer com cada uma. Isso é o que permite a uma regra
sazonal (ex.: Black Friday, só em novembro) processar um período de três meses sem
efeito nos outros dois.

**`apuracao_base: pandas.DataFrame`** - o baseline congelado, concatenado para
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
  de qualquer forma), não lê variável de ambiente, não escreve em disco fora do
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
propaga e o worker classifica a execução como `erro_codigo` - o job para, não
devolve número parcial. O mesmo vale para um retorno que não seja um `dict` com as
duas chaves esperadas, ou cujos DataFrames não tenham as colunas exigidas: o validador
de saída (`validar-saida.py`) rejeita antes de o resultado ser aceito, e essa rejeição
também vira `erro_codigo`. Não existe "resultado parcial aceito" - ver ARCHITECTURE.md
§1.5, "a regra é simulada por inteiro".
