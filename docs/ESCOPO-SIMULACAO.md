# Synapse — Escopo da simulação a partir do dataset Dom Rock

Este documento delimita **o que o Synapse consegue simular** com os dados que a Dom Rock
efetivamente entregou em `dataset_domrock/`, e **o que fica fora de escopo** por ausência
de dado. Complementa a ARCHITECTURE.md §1.2–1.5 (o que "simular" significa) e detalha os
pontos em aberto §15.2 (itens 3 a 6). É insumo direto de T-030 (regras base), T-032
(baselines) e T-036 (regra de referência), e serve de recorte para a sprint review.

O conteúdo das bases foi verificado abrindo os 13 arquivos `.xlsx` do dataset.

---

## 1. O que a Dom Rock entregou

### 1.1. As três bases

| Base | Arquivos | Conteúdo verificado |
| --- | --- | --- |
| **RH** | 6 × `BASE RH_<MÊS>25.xlsx`, aba `BASE HC` | ~460–469 funcionários por competência. Colunas: `Data_Ref`, `Cod_Marca`, `Descri_Marca`, `Cod_Loja`, `Descr_Loja`, `Matricula`, `Data_Admiss`, `Data_Demiss`, `Cod_Cargo`, `Descri_Cargo`. `Data_Demiss` preenchida em 4 a 8 linhas por mês. `BASE RH_SET25` tem uma coluna extra `VENDAS R$`. |
| **Vendas** | 6 × `BASE_VENDAS_<MÊS>25.xlsx`, aba `VENDAS` | ~5.000 lançamentos por competência, um por venda, ligados por `Matricula`. Colunas: `Date_Ref`, `Cod_Marca`, `Descr_Marca`, `Cod_Loja`, `Descr_Loja`, `Matricula`, `Vlr _Venda`. |
| **Comissionamento** | 1 × `BASE_COMMISS_FINAL.xlsx`, aba `Commission` | Tabela única de 30 linhas (6 marcas × 5 descrições de cargo). `%_Comiss` vem como **fração** (`0.025` = 2,5%). **Não varia por competência.** Apesar do nome, não é um resultado apurado. |

**Dimensões do domínio:** 6 marcas (10 PRETO, 20 BRANCO, 30 AZUL, 40 VERMELHO, 50 AMARELO,
60 CINZA), 4 códigos de cargo (100 VENDEDOR LOJA, 150 GERENTE, 200 VENDEDOR BALCÃO,
300 ASSISTENTE DE VENDAS), ~79 lojas.

**O cargo 150 é duplo.** Aparece como `GERENTE DE LOJA` e como `GERENTE QUIOSQUE`, com o
mesmo código e percentuais diferentes na tabela de comissão. O join RH → Comissionamento
precisa usar `Descri_Cargo`, não só `Cod_Cargo` (§15.2 item 5).

### 1.2. As seis competências

| Competência | Funcionários (RH) | Venda total do mês | `Date_Ref` das vendas |
| --- | --- | --- | --- |
| Jul/2025 | 322 | R$ 18,68 mi | dia 1º |
| Ago/2025 | 465 | R$ 10,35 mi | dia 1º |
| Set/2025 | 468 | R$ 9,73 mi | dia 1º |
| Out/2025 | 460 | R$ 9,78 mi | dia 1º |
| **Nov/2025** | 469 | R$ 13,85 mi | **dia 1º + datas reais 24 a 28/11** |
| Dez/2025 | 467 | R$ 13,24 mi | dia 1º |

Só a base de vendas de **novembro** carrega data real dentro do mês (4.279 linhas no dia 1º,
721 distribuídas entre 24 e 28/11 — a janela da Black Friday). Nos demais meses toda venda
está datada no dia 1º, então **não há granularidade intra-mês** (§15.2 item 4; T-027).

### 1.3. O que não veio

- **Não há gabarito.** Nenhum arquivo traz o comissionamento que a empresa de fato pagou.
  Não é possível calcular a partir das tabelas — sairia a nossa própria apuração (§1.3 do
  ARCHITECTURE.md). Pedido ao parceiro: um total agregado por competência (§15.2 item 4).
- **Não há orçamento.** É parâmetro informado pelo usuário na simulação (§1.3).
- **Não há base de eventos de RH.** Afastamentos, férias, licença maternidade e correções
  cadastrais existem só na prosa do `Especificacao.md`, seção "Intercorrências" (§1.2,
  camada 2; T-028).

---

## 2. O critério de escopo

> **Uma regra é simulável quando todo campo que ela referencia existe nas três bases.**

O agente gera código Python arbitrário (§1.4), então o escopo **não é uma lista fechada de
formatos de regra**. O limite é de dado: uma regra que só toca marca, loja, cargo, matrícula,
valor de venda, data da venda (novembro), data de admissão ou data de demissão pode ser
simulada, mesmo com um formato inédito. Uma regra que depende de qualquer outra dimensão
não pode — não por limitação do sistema, mas porque o número sairia de um dado que não
existe.

---

## 3. O que PODE ser simulado

### 3.1. Regras base — valem em toda competência

Implementadas uma vez como código determinístico (§1.2, camada 1; T-030):

- Aplicar o `%` por marca + cargo sobre a venda consolidada de cada funcionário no mês.
- Comissão do gerente (cargo 150) sobre a **venda total da loja** (soma de todos os
  funcionários da loja, inclusive o gerente).
- **Proporcional por dias trabalhados na admissão** — quando `Data_Admiss` cai dentro da
  competência, a comissão é multiplicada por `(dias do mês − dia da admissão) ÷ dias do mês`.
- **Proporcional por dias trabalhados na demissão** — quando `Data_Demiss` cai dentro da
  competência, a comissão é multiplicada por `(dia da demissão) ÷ dias do mês`.

### 3.2. Regras da competência — mudanças de política propostas pelo usuário

Traduzidas em código gerado (§1.2, camada 3). Todas as formas do catálogo do parceiro têm
suporte de dado:

| Forma de regra | Exemplo real no dataset | Observação |
| --- | --- | --- |
| Alterar o `%` de uma combinação marca + cargo | Ago: marca 10 / cargo 300 → 1,75% | — |
| Aplicar a tabela de `%` de uma marca em outra | Set: `%` da marca 20 nos cargos da marca 10 | — |
| Acréscimo de `%` a uma marca, com exclusão de cargo | Out: marca 30 +0,5%, exceto gerentes | — |
| Acréscimo de `%` restrito a um intervalo de datas | Nov: Black Friday +1% de 24 a 30/11 | **Só novembro** tem data de venda intra-mês |
| Bônus fixo por faixa de venda **individual** (mensal por matrícula) | Dez: 40–50 mil → R$ 3.500; 50–60 mil → R$ 4.000; > 60 mil → R$ 4.500 | "Venda individual" = total consolidado no mês, não transação |
| Bônus fixo por faixa de venda **total da loja** | Dez: loja > 120 mil → bônus do gerente por faixa | — |
| Bônus fixo em R$ para uma lista de matrículas | Ago: R$ 500 para 8 matrículas | A lista entra como dado, não como código |
| Bônus somado à base de cálculo de vendas de uma lista | Set: +R$ 20.000 na base de 9 matrículas | — |
| Bônus condicionado a atributo cadastral | Out: admitidos até 10/10 no cargo 100 → +R$ 1.000 | Usa `Data_Admiss` + `Cod_Cargo` |
| Exclusão de cargo, marca ou loja de qualquer regra acima | Out: "não se aplica aos gerentes" | — |

### 3.3. Sobre quais competências

Cinco competências são base sólida: **Ago, Set, Out, Nov e Dez de 2025**.
**Julho fica fora** até revisão dos dados (ver §5).

---

## 4. O que NÃO pode ser simulado

### 4.1. A dimensão não existe no dataset

Qualquer regra que dependa de um destes recortes é inviável com os dados atuais:

- **Canal de venda** — nenhuma coluna corresponde. Isso afeta o próprio núcleo da regra
  descrito no backlog (validade, **canal**, produto, equipe, %); a reconciliação de
  vocabulário está em aberto (§15.2 item 3; T-084).
- **Meta ou cota** — individual, por loja ou por equipe; e atingimento de meta.
- **Produto, SKU, categoria, linha ou margem** — a venda tem valor e marca, nada abaixo disso.
- **Cliente, forma de pagamento, ticket médio, desconto.**
- **Atributos de pessoa ausentes no RH** — gênero, idade, faixa de tempo de casa (só existe
  a `Data_Admiss` crua), carga horária, jornada, turno.
- **Hora, turno ou canal de cada venda.**
- **Regra por transação individual** — o dado de transação existe, mas fora de julho o maior
  lançamento é ~R$ 5.100; qualquer limiar realista ("venda acima de R$ X numa só compra")
  não pega nenhuma linha. A própria especificação lê "venda individual" como o total mensal
  consolidado.

### 4.2. O dado não existe de forma alguma

- **Afirmar valor absoluto** ("a empresa teria pago R$ X") — sem gabarito, a simulação só
  sustenta **comparação relativa** ao baseline ("esta regra aumenta o custo em 6,5%"). Como o
  orçamento informado pelo usuário é confrontado com o total absoluto, o alerta de
  inviabilidade recai sobre um total auto-apurado, não sobre uma verdade externa (§1.3).
- **Projeção de vendas futuras** — seis meses, sem ciclo sazonal completo e sem ano anterior.
  A arquitetura descarta forecast: introduziria mais incerteza do que o efeito a medir (§1.3).
- **Resposta comportamental** — o backtest assume que as pessoas venderiam o mesmo sob a
  regra nova. Uma comissão maior pode motivar mais vendas; isso o modelo não captura, e é
  limitação a declarar ao usuário (§1.3).

---

## 5. Simulável, mas só depois de um passo de preparação

Não são impossíveis; dependem de trabalho de dados que ainda não foi feito:

| Item | O que falta | Tarefa |
| --- | --- | --- |
| Regras que interagem com **afastamento, férias ou licença maternidade** (regras base 5e–5g) | Extrair os eventos da prosa do `Especificacao.md` e congelar com conferência humana | T-028, T-029 |
| **Gerente rateado entre lojas** (caso MATRIC-293, jul) | Lógica nova nas regras base, além do fato em si | T-030 |
| **Julho/2025** | RH com 322 funcionários (vs ~465), vendas cobrindo 54 de 78 lojas, `Vlr _Venda` até R$ 78,5 mil (demais meses: máx ~R$ 5,1 mil), venda/matrícula mediana R$ 66,7 mil (vs R$ 23–32 mil). Escala e estrutura diferentes — decidir se normaliza ou exclui | T-025, T-026 |
| **Matrículas órfãs** — em Vendas sem correspondência no RH (Ago 3, Set 1, Out 1, Nov 2, Dez 5) | Regra de tratamento (ignorar, imputar, reportar) | T-025 (§15.2 item 6) |
| **`Date_Ref` com semântica dupla** na base de vendas de novembro | Separar competência de data real antes de agrupar, senão a Black Friday vira competência à parte | T-027 |

---

## 6. Ressalvas que valem para toda simulação

1. **Resultado é sempre relativo.** Diferença e variação percentual contra o baseline são
   confiáveis; o valor absoluto carrega a imprecisão de interpretação das regras (que se
   cancela na diferença, mas não no total).
2. **O baseline é auto-apurado**, não oficial. Reapurar todos os seis baselines é barato e
   previsto; se o total agregado do parceiro chegar depois de T-032 e não bater, os baselines
   se deslocam (§15.2 item 4).
3. **A regra é simulada por inteiro** (§1.5). Elemento sem implementação correspondente é
   falha de geração e para o job — não existe simulação parcial.
4. **Janela de datas só funciona em novembro.** Uma regra sazonal proposta para qualquer
   outro mês não tem onde se posicionar: todas as vendas estão no dia 1º.

---

## 7. Relação com pontos em aberto e tarefas

- **§15.2 item 3** (vocabulário: "canal") — bloqueia regras de núcleo que usem canal; T-084.
- **§15.2 item 4** (sem gabarito) — fixa o escopo em comparação relativa; T-025, T-032.
- **§15.2 item 5** (cargo 150 duplo) — condiciona o join e a regra do gerente; T-025, T-030.
- **§15.2 item 6** (matrículas órfãs, alinhamento de colunas do RH) — T-025, T-026.
- **T-030** consome as regras base desta lista; **T-031** as asserções que as protegem;
  **T-032** apura e congela os baselines das cinco competências em escopo.
