# Synapse — Escopo da simulação a partir do dataset Dom Rock

Este documento delimita o que pode ser apurado com o dataset Dom Rock e as limitações decorrentes dos dados disponíveis. Complementa [ARCHITECTURE.md](ARCHITECTURE.md) e o [fluxo aprovado para a Sprint 2](FLUXO-SPRINT-2.md). Ter suporte de dado não comprova que a geração de código de todos os construtos já foi implementada ou validada.

O conteúdo das bases foi verificado abrindo os 13 arquivos `.xlsx` do dataset.

---

## 1. O que a Dom Rock entregou

### 1.1. As três bases

| Base | Arquivos | Conteúdo verificado |
| --- | --- | --- |
| **RH** | 6 × `BASE RH_<MÊS>25.xlsx`, aba `BASE HC` | ~460–469 funcionários por competência. Colunas: `Data_Ref`, `Cod_Marca`, `Descri_Marca`, `Cod_Loja`, `Descr_Loja`, `Matricula`, `Data_Admiss`, `Data_Demiss`, `Cod_Cargo`, `Descri_Cargo`. `Data_Demiss` preenchida em 4 a 8 linhas por mês. `BASE RH_SET25` tem uma coluna extra `VENDAS R$`. |
| **Vendas** | 6 × `BASE_VENDAS_<MÊS>25.xlsx`, aba `VENDAS` | ~5.000 lançamentos por competência, um por venda, ligados por `Matricula`. Colunas: `Date_Ref`, `Cod_Marca`, `Descr_Marca`, `Cod_Loja`, `Descr_Loja`, `Matricula`, `Vlr _Venda`. |
| **Comissionamento** | 1 × `BASE_COMMISS_FINAL.xlsx`, aba `Commission` | Tabela única de 30 linhas (6 marcas × 5 descrições de cargo). `%_Comiss` vem como **fração** (`0.025` = 2,5%). **Não varia por competência.** Apesar do nome, não é um resultado apurado. |

**Dimensões do domínio:** 6 marcas (10 PRETO, 20 BRANCO, 30 AZUL, 40 VERMELHO, 50 AMARELO, 60 CINZA), 4 códigos de cargo (100 VENDEDOR LOJA, 150 GERENTE, 200 VENDEDOR BALCÃO, 300 ASSISTENTE DE VENDAS), ~79 lojas.

**O cargo 150 tem duas descrições na origem.** A fonte bruta traz `GERENTE DE LOJA` e `GERENTE QUIOSQUE` com o mesmo código e percentuais distintos. A T-026 resolveu essa ambiguidade pela decisão `CANONICAL_MANAGER_RATE`: no dataset canônico, ambas as descrições usam a taxa de `GERENTE DE LOJA`, e `Descri_Cargo` é apenas descritivo — o join de comissionamento usa `Cod_Cargo` + `Cod_Marca` + competência.

### 1.2. Competências recebidas e competências publicadas

| Competência | Funcionários (RH) | Venda total do mês | `Date_Ref` das vendas |
| --- | --- | --- | --- |
| Jul/2025 | 322 | R$ 18,68 mi | dia 1º |
| Ago/2025 | 465 | R$ 10,35 mi | dia 1º |
| Set/2025 | 468 | R$ 9,73 mi | dia 1º |
| Out/2025 | 460 | R$ 9,78 mi | dia 1º |
| **Nov/2025** | 469 | R$ 13,85 mi | **dia 1º + datas reais 24 a 28/11** |
| Dez/2025 | 467 | R$ 13,24 mi | dia 1º |

A Dom Rock entregou seis competências brutas (Jul–Dez/2025), mas a T-026 publica no dataset canônico somente **cinco competências: Ago–Dez/2025**. Julho é mantido apenas como evidência histórica para reconciliação e está excluído da simulação pela decisão `EXCLUDE_2025_07` registrada no relatório de normalização.

Só a base de vendas de **novembro** carrega data real dentro do mês (4.279 linhas no dia 1º, 721 distribuídas entre 24 e 28/11 — a janela da Black Friday). Nos demais meses toda venda está datada no dia 1º, então **não há granularidade intra-mês** (T-027).

### 1.3. O que não veio

- **Não há gabarito.** Nenhum arquivo traz o comissionamento que a empresa de fato pagou. Não é possível calcular a partir das tabelas — sairia a nossa própria apuração (§1.3 do ARCHITECTURE.md). Pedido ao parceiro: um total agregado por competência (ARCHITECTURE.md §15.2).
- **Não há orçamento.** É parâmetro informado pelo usuário na simulação (§1.3).
- **Não há base de eventos de RH.** Afastamentos, férias, licença maternidade e correções cadastrais existem só na prosa do `Especificacao.md`, seção "Intercorrências" (§1.2, camada 2; T-028).

---

## 2. O critério de escopo

> **Uma regra é simulável quando todo campo que ela referencia existe nas três bases.**

O agente gera código Python arbitrário (§1.4), então o escopo **não é uma lista fechada de formatos de regra**. O limite é de dado: uma regra que só toca marca, loja, cargo, matrícula, valor de venda, data da venda (novembro), data de admissão ou data de demissão pode ser simulada, mesmo com um formato inédito. Uma regra que depende de qualquer outra dimensão não pode — não por limitação do sistema, mas porque o número sairia de um dado que não existe.

---

## 3. O que PODE ser simulado

### 3.1. Regras base — valem em toda competência

Implementadas uma vez como código determinístico (§1.2, camada 1; T-030):

- Aplicar o `%` por marca + cargo sobre a venda consolidada de cada funcionário no mês.
- Comissão do gerente (cargo 150) sobre a **venda total da loja** (soma de todos os funcionários da loja, inclusive o gerente).
- **Proporcional por dias trabalhados na admissão** — quando `Data_Admiss` cai dentro da competência, a comissão é multiplicada por `(dias do mês − dia da admissão) ÷ dias do mês`.
- **Proporcional por dias trabalhados na demissão** — quando `Data_Demiss` cai dentro da competência, a comissão é multiplicada por `(dia da demissão) ÷ dias do mês`.

### 3.2. Regras da competência — mudanças de política propostas pelo usuário

Traduzidas em código gerado (§1.2, camada 3). Todas as formas do catálogo do parceiro têm suporte de dado:

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

**Atualmente, cinco competências canônicas estão no escopo da simulação: Ago, Set, Out, Nov e Dez de 2025.** Julho foi recebido na base bruta, mas não é publicado pela T-026 e, portanto, não possui baseline corrente.

A simulação roda sobre um **período**, não sobre um mês. O usuário escolhe quais competências entram — por padrão todas — e o job as agrega num total único, com um veredito único. Não existe uma simulação por competência.

---

## 4. O que NÃO pode ser simulado

### 4.1. A dimensão não existe no dataset

Qualquer regra que dependa de um destes recortes é inviável com os dados atuais:

- **Canal de venda** — nenhuma coluna corresponde. O núcleo da regra não usa "canal": a DEC-084 fixou **loja** como o recorte de agrupamento, por ser a menor divisão de vendas e de lotação que as bases materializam.
- **Meta ou cota** — individual, por loja ou por equipe; e atingimento de meta.
- **Produto, SKU, categoria, linha ou margem** — a venda tem valor e marca, nada abaixo disso.
- **Cliente, forma de pagamento, ticket médio, desconto.**
- **Atributos de pessoa ausentes no RH** — gênero, idade, faixa de tempo de casa (só existe a `Data_Admiss` crua), carga horária, jornada, turno.
- **Hora, turno ou canal de cada venda.**
- **Regra por transação individual** — o dado de transação existe, mas fora de julho o maior lançamento é ~R$ 5.100; qualquer limiar realista ("venda acima de R$ X numa só compra") não pega nenhuma linha. A própria especificação lê "venda individual" como o total mensal consolidado.

### 4.2. O dado não existe de forma alguma

- **Afirmar valor absoluto** ("a empresa teria pago R$ X") — não há gabarito do que foi efetivamente pago. A simulação produz valores absolutos e diferenças conforme as regras implementadas; ambos dependem da interpretação dessas regras e não substituem a conferência externa. O orçamento é confrontado com esse total autoapurado (§1.3).
- **Projeção de vendas futuras** — cinco competências canônicas publicadas, sem ciclo sazonal completo e sem ano anterior. A arquitetura descarta forecast: introduziria mais incerteza do que o efeito a medir (§1.3).
- **Resposta comportamental** — o backtest assume que as pessoas venderiam o mesmo sob a regra nova. Uma comissão maior pode motivar mais vendas; isso o modelo não captura, e é limitação a declarar ao usuário (§1.3).

---

## 5. Itens que exigem ou exigiram preparação

Alguns destes pontos já foram resolvidos pelas tarefas de preparação; os demais continuam registrados aqui para deixar explícito o que precisa ser resolvido caso o escopo publicado mude:

| Item | O que falta | Tarefa |
| --- | --- | --- |
| Regras que interagem com **afastamento, férias ou licença maternidade** | A T-028 congelou os eventos de RH; a T-030 os consome como dados normalizados. A conferência da extração continua pertencendo à trilha T-028/T-029 | T-028, T-029, T-030 |
| **Gerente rateado entre lojas** (caso MATRIC-293, jul) | Fora das regras base atuais. Se julho voltar ao dataset publicado, o fato precisa estar na tabela de eventos e a lógica específica da competência precisa ser definida antes da reapuração | DEC-090 |
| **Julho/2025** | A T-026 concluiu que a competência não é publicável com as demais e a marcou como evidência histórica (`EXCLUDE_2025_07`) | T-026 |
| **Matrículas órfãs** — vendas sem correspondência no RH | A T-026 definiu `DISCARD_UNRESOLVED_ORPHAN_SALES`; a T-030 preserva a política e emite aviso se receber órfã diretamente | T-026, DEC-090 |
| **`Date_Ref` com semântica dupla** na base de vendas de novembro | Separar competência de data real antes de agrupar, senão a Black Friday vira competência à parte | T-027 |

---

## 6. Ressalvas que valem para toda simulação

1. **Valores são apurações do modelo implementado.** Totais e diferenças podem ser conferidos internamente; sem gabarito, não há garantia de correspondência ao pagamento real. Usar os mesmos dados no baseline e na proposta não garante cancelamento dos erros de interpretação.
2. **O baseline é auto-apurado**, não oficial. Reapurar os cinco baselines atualmente publicados é barato e previsto; se o total agregado do parceiro chegar depois de T-032 e não bater, os baselines se deslocam (§15.2 item 4).
3. **A regra é simulada por inteiro** (§1.5). Elemento sem implementação correspondente é falha de geração e para o job — não existe simulação parcial.
4. **Janela de datas só funciona em novembro.** Uma regra sazonal proposta para qualquer outro mês não tem onde se posicionar: todas as vendas estão no dia 1º.

---

## 7. Cenários de vendas planejados para a Sprint 2

O cenário histórico mantém as vendas observadas. E5 acrescenta uma análise hipotética com a regra mantida e uma taxa uniforme aplicada ao volume existente, preservando a proporção entre pessoas, lojas, marcas e competências.

Não existe nos dados entregues uma relação estimada entre mudança da taxa de comissão e crescimento das vendas por funcionário. A tabela de comissão é fixa por marca e cargo nas competências brutas recebidas. Sem evidência adicional da Dom Rock, não se pode afirmar que aumentar a comissão em X produziria um aumento de vendas em Y.

Todos os candidatos precisam ser calculados deterministicamente no worker. A LLM interpreta a regra e coordena o fluxo, sem calcular valores de venda, comissão ou crescimento.

O critério econômico pesquisado e a existência de solução precisam ser explícitos. Para uma regra proporcional, aumentar vendas também aumenta comissão e pode piorar o enquadramento em um orçamento absoluto fixo. Faixas e bônus podem introduzir descontinuidades; bisseção exige monotonicidade no trecho pesquisado. O cenário deve informar quando não existe solução no intervalo considerado.

## 8. Rastreabilidade planejada

“Quando” é a competência mensal, com a ressalva de datas reais de novembro/Black Friday. Os resultados atuais têm totais e quebras independentes de diferença por elemento, loja, marca, cargo e competência.

Essas quebras não contêm o valor absoluto por pessoa nem permitem cruzar pessoa, loja e mês. A Sprint 2 prevê matrícula, valores absolutos e preservação dos dataframes resultantes. Falta confirmar se a consulta exige totais separados ou linhas conjuntas de matrícula × loja × competência; a persistência e os contratos devem atender à granularidade escolhida.

## 9. Preparação e referências

- T-026: publica agosto a dezembro de 2025, resolve o cargo 150 com `CANONICAL_MANAGER_RATE` e vendas órfãs com `DISCARD_UNRESOLVED_ORPHAN_SALES`; julho permanece excluído.
- T-030 e T-031: regras base e asserções da apuração.
- T-032: baselines congelados das cinco competências canônicas.
- [Fluxo da Sprint 2](FLUXO-SPRINT-2.md): chatbot, vendas e evolução dos resultados.
