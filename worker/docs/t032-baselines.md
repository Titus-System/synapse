# T-032 — Baselines de agosto a dezembro de 2025

**Baseline não é gabarito.** Estes arquivos são a nossa apuração determinística
das regras vigentes do `dataset_domrock/Especificacao.pdf`. Não representam
comprovação do que a empresa pagou e não foram validados contra um total externo.

São **cinco competências**, conforme T-026 e confirmação do Scrum Master em
15/09/2026. Julho continua somente como evidência histórica e não foi reintroduzido.
Congelamento inicial: **17/09/2026**. Formato republicado como **versão 2** para alinhar
o baseline ao contrato T-034, sem alterar as comissões individuais nem os totais congelados.

| Competência | Matrículas elegíveis | Total de comissão |
| --- | ---: | ---: |
| 2025-08 | 497 | R$ 363.021,46 |
| 2025-09 | 530 | R$ 424.628,68 |
| 2025-10 | 537 | R$ 698.465,53 |
| 2025-11 | 546 | R$ 508.382,32 |
| 2025-12 | 562 | R$ 1.305.396,25 |

## Arquivos e leitura

`sandbox/data/domrock/baselines/baseline-YYYY-MM.jsonl` é publicado diretamente no
formato de `apuracao_base` do contrato T-034: uma linha por matrícula elegível e
competência, com `matricula`, `cod_loja`, `cod_marca`, `cod_cargo`, `competencia` e
`comissao`. O arquivo pode ser concatenado entre competências e somado diretamente,
sem filtro por nível e sem adaptação de colunas.

`cod_marca` é obtido do RH da própria competência por `competencia + matricula`. Durante
o congelamento, a rastreabilidade calculada também precisa apontar para exatamente uma
marca e essa marca precisa ser a mesma do RH. Se uma matrícula passar a ter componentes
de comissão de marcas diferentes, o build falha explicitamente: nenhuma marca é escolhida
em silêncio.

Os detalhes auditáveis que antes coexistiam no mesmo JSONL foram preservados em
`sandbox/data/domrock/baselines/auditoria/baseline-YYYY-MM.jsonl`. Esse artefato mantém
os mesmos bytes dos antigos baselines, com os três níveis da apuração:

| `nivel` | Conteúdo | Chave no mês |
| --- | --- | --- |
| `total` | Total e resultado das três asserções | Uma linha |
| `loja` | Comissão da loja | `cod_loja` |
| `matricula` | Comissão, base ajustada, cargo, loja e rastreabilidade individual | `matricula` |

Nos arquivos de auditoria, os três níveis representam a mesma apuração; portanto é
necessário filtrar `nivel` antes de somar. Eles não são entrada do harness.

Exemplo de consumo do baseline contratual:

```python
baseline = pandas.read_json(caminho, lines=True)
total = float(baseline["comissao"].sum())
```

O teste `contracts/harness/testar-contrato.py` lê os cinco arquivos reais diretamente,
confere tipos, unicidade, dimensões do RH e os valores congelados, e executa o exemplo
do contrato sobre os meses concatenados. O workflow `Validar contratos` também roda
quando os dados ou seus geradores mudam, mesmo sem alteração em `contracts/`.

O gerador não depende de pandas. Usa listas, Decimal e a biblioteca padrão.
Valores publicados são BRL com duas casas; os cálculos não arredondam cada venda
nem cada adicional. Arredondam uma vez por matrícula (`ROUND_HALF_UP`), depois
somam essas parcelas com Decimal para produzir quebras e total exatamente iguais.

`baselines/manifesto.json` registra competências, totais, quantidades, asserções,
SHA-256 do baseline contratual e SHA-256 do respectivo artefato de auditoria, além
das entradas e do código do cálculo. Não contém horário de execução, caminhos
absolutos ou valores aleatórios.

`eventos_rh.jsonl` é uma conversão estrutural da fonte da T-028, com 32 eventos:
remove comentários e transforma cada objeto em uma linha, preservando IDs,
datas, competências e detalhes. `regras_competencia.jsonl` registra as 12 políticas
históricas com sua referência ao PDF; listas de matrículas ficam nesses dados.
`build_canonical_dataset.py` publica também a anotação dessas tabelas no schema,
para uma nova execução da T-026 não apagar o contrato dos artefatos da T-032.

## Regras implementadas

| Mês | Regras além da T-030 e dos eventos de RH |
| --- | --- |
| Agosto | R$ 500 finais às oito matrículas de 2g; taxa da marca 10/cargo 300 substituída por 1,75% (2h). |
| Setembro | R$ 20.000 na base das nove matrículas de 3f; taxas da marca 20 aplicadas aos cargos da marca 10 (3g). |
| Outubro | +0,5 **ponto percentual** para marca 30, exceto cargo 150 (4g); R$ 1.000 finais para cargo 100 admitido até 10/10 (4h). |
| Novembro | Vendas com data real entre 24 e 30/11, inclusive: +1 ponto percentual para não gerentes e +0,5 para cargo 150, sobre as vendas da loja (5f/5g). |
| Dezembro | Marcas 40/50/60: +1 ponto percentual; marca 30: +0,5, sempre excluindo gerentes (6f/6g). Bônus por faixa individual de marcas 10/20 (6h) e por total de loja para gerentes (6i). |

No dataset publicado, agosto não possui funcionário da combinação marca 10/cargo
300. A política 2h está implementada e testada com um caso numérico, mas não muda
o total desse arquivo. Não foram criados funcionários para forçar um efeito.

### Ordem de cálculo

1. Selecionar a competência e aplicar as correções de RH da T-028 em memória.
2. Ajustar a tabela de percentuais e calcular as vendas reais elegíveis.
3. Somar bônus de base e comissão adicional por data, antes das proporções.
4. Aplicar admissão/demissão, férias e afastamento/piso da T-030.
5. Acrescentar os bônus explicitamente definidos como valor final.
6. Arredondar por matrícula e executar obrigatoriamente as três asserções.

O bônus de base de setembro pertence somente à pessoa beneficiada: não é venda
fictícia e não aumenta a comissão de outros gerentes. O adicional de novembro
também passa pelas proporções/piso; somá-lo depois do piso pagaria um extra que
a regra de piso não determina. Vendas sem `data_venda` não ganham Black Friday,
mesmo que `data_ref` contenha uma data dentro da janela.

### Interpretações registradas para revisão

- **Outubro:** “admitidos até 10/10” foi aplicado literalmente como
  `data_admiss <= 2025-10-10`, incluindo admissões de meses/anos anteriores,
  desde que a pessoa seja elegível na competência e tenha cargo 100. Não foi
  acrescentada uma restrição “admitidos em outubro” ausente no PDF. Isso concede
  345 bônus de R$ 1.000 e explica o crescimento de outubro. É uma premissa material
  que deve permanecer visível na revisão; mudar sua leitura exige recongelamento.
- **Faixas de dezembro:** prevalece “superior a R$ 40 mil/120 mil”. A primeira
  faixa é `(40.000, 50.000]`, depois `(50.000, 60.000]` e `>60.000`; para loja,
  `(120.000, 140.000]`, `(140.000, 160.000]` e `>160.000`. Os limites textuais
  “50.001/60.001” não criam lacunas para valores em centavos. As fronteiras são testadas.
- **Bônus individuais e gerentes em dezembro:** 6h não exclui cargo 150. Um gerente
  das marcas 10/20 pode receber o bônus pela própria venda e o bônus pela loja,
  se satisfizer ambos os critérios. A base individual nunca é substituída pela loja.
- **Eventos de RH:** mantidas as datas inclusivas da DEC-090/T-028, inclusive
  maternidade com data final estimada. MATRIC-318 permanece com férias de 02 a
  15/12, como já registrado na T-028; o comentário da fonte declara incerteza
  na inversão das datas do PDF. A T-032 não resolve nem esconde essa incerteza.
- **Lotação:** a quebra da comissão é pela loja do RH, preservando a T-030.
  A venda pode ocorrer em outra loja/marca; essas dimensões reais continuam na
  rastreabilidade. Para gerentes, usa-se a venda real da loja de lotação.

Estas escolhas são explícitas e determinísticas, não confirmação do parceiro.
Mudanças posteriores devem ter revisão e novo congelamento, com atualização
dos testes consumidores de T-036/T-076; não substitua silenciosamente os números.

## Reprodução e proteção do congelamento

Aplique a T-031 antes desta tarefa. Na pasta `worker/`:

```bash
# Conferir exatamente os bytes versionados, sem escrever:
poetry run python -m scripts.build_baselines --check

# Produzir uma cópia para inspeção:
poetry run python -m scripts.build_baselines --output-dir /tmp/synapse-baselines

# Testes e gate do worker:
poetry run pytest tests/app/sandbox/test_regras_competencia.py tests/scripts/test_build_baselines.py
sh verify.sh
```

No Windows, substitua `/tmp/synapse-baselines` por uma pasta temporária local.
Rodar sem parâmetros também confere os arquivos existentes e só regrava se os
bytes forem iguais. Divergência de entrada, cálculo ou artefato interrompe antes
de escrever. `--atualizar` permite um novo congelamento após revisão explícita.

A preparação valida `published_competencias` e o estado `ready` da T-026.
Calcula e valida os cinco meses antes de escrever qualquer artefato; falha de
asserção é erro no motor. A suíte verifica reprodução em processos com
`PYTHONHASHSEED` diferentes, conciliação exata, políticas mensais, preservação dos
eventos e recusa de sobrescrita silenciosa.

## Limites e integração

O código histórico está em `app/sandbox/regras_competencia.py`.
`regras_base.apurar` ganhou apenas um argumento nomeado opcional de ajustes;
chamadas existentes mantêm o cálculo base. O motor faz a aritmética das duas
camadas antes da finalização T-031, evitando arredondamento prematuro e dupla
aplicação de proporções. Nenhuma tabela de entrada é alterada.

Estes arquivos são dados congelados para a imagem da **T-033**. A T-032 não altera
Dockerfile, não inicia containers e não recalcula baseline por job. O orçamento
não está nesses dados nem entra no motor. Comparação do simulado com baseline,
veredito e publicação continuam nas tarefas T-065/T-066/T-067.
