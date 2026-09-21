# **ESPECIFICAÇÃO TESTE COMISSIONAMENTO** 

## **OBJETIVO:** 

Realizar o cálculo de comissionamento mensal dos funcionários considerando as seus respectivos % de comissionamento, as suas relações com a legislação trabalhista e as suas excepcionalidades decorrentes do seu respectivo cargo utilizando como base de apuração o desenvolvimento de aplicação em IA Generativa, com base em Modelos LLM existentes. 

## **BASES ENVOLVIDAS:** 

1. Base de RH – lista com todos os funcionários da empresa no período analisado 

2. Base de vendas – resumo das vendas do mês 

3. Base comissionamento - % de comissionamento por cargo e marca 

## **DETALHAMENTO BASE** 

## **Base RH** 

- a) Date_Ref – data competência do processamento 

- b) Cod_Marca – código da marca 

- c) Descr_Marca – descrição da marca 

- d) Cod_Loja – código da loja 

- e) Descr_Loja - nome loja 

- f) Matricula – código do funcionário 

- g) Data Admiss – data de admissão do funcionário 

- h) Data_Demiss – data de demissão do funcionário 

- i) Cod_Cargo – código do cargo 

- j) Descr_Cargo – nome do cargo 

## **Base Vendas** 

- a) Date_Ref 

- b) Cod_Marca 

- c) Descr_Marca 

- d) Cod_Loja 

- e) Descr_Loja 

- f) Matricula 

- g) Vlr _Venda – Valor das vendas individuais 

## **Base de Comissionamento** 

- a) Cod_Marca 

- b) Descr_Marca 

- c) Cod_Cargo 

- d) Descri_Cargo 

- e) %_Comiss - % de comissionamento por cargo e por marca 

## **ESPECIFICAÇÃO – PROCESSAMENTO BASE** 

1. O processamento deve ser realizado respeitando a data de competência de cada base: Ex: Base RH mês1 com base de Vendas mês1 

2. Relacionar a “Base de Vendas” com a “Base de RH” considerando a matrícula de cada funcionário – objetivo: obter as vendas individuais por funcionário 

3. Relacionar a “Base de Vendas” com a “Base de RH” considerando o cod_loja – objetivo: obter as vendas consolidadas por loja 

4. Consolidar as vendas mensais dos funcionários por Matrícula e consolidar as vendas das lojas pelo Cod_Loja 

5. Regras 

   - a. Geral - Aplicar o respectivo % de comissionamento do arquivo “Base de Comissionamento” a cada funcionário considerando: a Matrícula, o Cod_Marca e o Cod_Cargo 

   - b. Gerente - Para o código de cargo Gerente (150) a aplicação do % de comissionamento se dará pela venda total da loja apurada pela soma de todos os funcionários existente em cada loja, inclusive o gerente. 

   - c. Admissão - Caso algum funcionário seja admitido no mês de competência (Data_Admiss) o seu comissionamento será calculado proporcionalmente aos dias trabalhados, sendo que para os gerentes se aplica a mesma regra, porém a proporcionalidade do valor de comissionamento se dará em cima da venda total da loja. Ex: Admitido no dia 10 de outubro. Comissionamento = Vlr Apurado de comissionamento dividido por 31 (qtde dias do mês de outubro) e multiplicado por 21 (31-10=dias efetivamente trabalhados). 

   - d. Demissão – Caso algum funcionário seja demitido no mês de competência (Data_Demiss) o seu comissionamento será calculado proporcionalmente aos dias trabalhados, sendo que para os gerentes se aplica a mesma regra, porém a proporcionalidade do valor de comissionamento se dará tbm pela venda total da loja. 

Ex: demitido no dia 10 de novembro. Comissionamento = Vlr Apurado de comissionamento dividido por 30 (qtde dias do mês de novembro) e multiplicado por 10 (dias efetivamente trabalhados). 

- e. Afastamento < 15 dias – funcionário afastado por atestado por um período menor que 15 dias terá direito a receber comissionamento proporcional as suas vendas no período trabalhado ou um valor fixo de R$3.500, dos 2 o maior. Para os gerentes se aplica a mesma regra, porém a proporcionalidade do valor de comissionamento se dará pela vlr de venda total da loja. 

   - Ex: funcionário afastado por 10 dias – venda de R$20.000 mil no mês. Sua base de comissionamento adicional será de R$10.000, ou seja 20.000 dividido por 20 (qtde de dias trabalhado) x 10 dias de afastamento. 

- f. Afastamento > 15 dias – funcionário afastado por um período maior que 15 dias terá direito a receber comissionamento proporcional as suas vendas somente por 15 dias de afastamento ou um valor fixo de R$3.500 dos 2 o maior. O restante dos dias não terá direito a nenhuma remuneração. Para os gerentes, se aplica a mesma regra, porém a proporcionalidade se dará pel valor total de venda da loja Ex: funcionário afastado por 20 dias – venda de R$8.000 mil no mês. Sua base de comissionamento adicional será de R$12.000, ou seja 8.000 dividido por 10 (30dias -20dias = qtde de dias trabalhado) x 15 dias de afastamento por lei. 

- g. Férias – funcionários em férias não terão direito a remuneração nos dias de gozo de férias, sendo que para os gerentes se aplica a mesma regra, porém a proporcionalidade do valor de comissionamento se dará pela valor da venda total da loja. 

## **INTERCORRÊNCIAS - TESTE** 

## **1. Julho de 2025** 

- a. Funcionário MATRIC-58 apresentou um atestado com afastamento no dia 10/07/25 e retornou no dia 25/07/25 

- b. Funcionário MATRIC-124 apresentou um atestado com afastamento do dia 21/07/25 até o dia 25/07/25 

- c. Funcionário MATRIC-400 apresentou um atestado com afastamento do dia 15/07/25 e retornou no dia 17/07/25 

- d. Funcionário MATRIC-485 apresentou um atestado com afastamento do dia 10/07/25 até o dia 29/07/25 

- e. Funcionário MATRIC-549 saiu de férias no período de 10/7/25 a 25/7/25 

   - f. Funcionário MATRIC-183 saiu de férias no período de 10/7/25 a 25/7/25 

   - g. O Gerente MATRIC-293 ficou 10 dias trabalhando na loja LOJA-5 e por isso precisa receber comissionamento proporcional a esta loja tbm além da sua loja original. 

**2. Agosto de 2025** 

   - a. Funcionário MATRIC-113 pediu afastamento no dia 4/08/25 e retornou no dia 11/08/25 

   - b. Funcionário MATRIC-126 apresentou um atestado com afastamento do dia 18/08/25 até o dia 8/09/25 

   - c. Funcionário MATRIC-137 apresentou um atestado com afastamento do dia 26/08/25 e retornou no dia 05/09/25 

   - d. Funcionário MATRIC-115 apresentou um atestado com afastamento do dia 01/08/25 até o dia 22/08/25 

   - e. Funcionário MATRIC-103 saiu de férias no período de 04/8/25 a 17/8/25 

   - f. Funcionário MATRIC-127 saiu de férias no período de 04/8/25 a 29/8/25 

   - g. Os funcionários abaixo receberam um bônus fixo de R$500 que deve ser acrescido no seu comissionamento final: 

      - i. MATRIC-134 

      - ii. MATRIC-135 

      - iii. MATRIC-14 

      - iv. MATRIC-141 

      - v. MATRIC-143 

      - vi. MATRIC-144 

      - vii. MATRIC-147 

      - viii. MATRIC-148 

   - h. Somente para este mês, o % de comissionamento da marca 10 no cargo 300 subiu para 1,75% 

**3. Setembro de 2025** 

   - a. Funcionário MATRIC-138 pediu afastamento no dia 8/09/25 e retornou no dia 12/09/25 

   - b. Funcionário MATRIC-126 apresentou um atestado com afastamento do dia 18/08/25 até o dia 8/09/25 

   - c. Funcionário MATRIC-137 apresentou um atestado com afastamento do dia 26/08/25 até o dia 05/09/25 

   - d. Funcionário MATRIC-17 saiu de férias no período de 1/9/25 a 30/9/25 

   - e. Funcionário MATRIC-127 saiu de férias no período de 15/9/25 a 26/9/25 

   - f. Os funcionários abaixo receberam um bônus fixo de R$20.000 por tempo de casa a ser acrescido na sua respectiva base de calculo de vendas para efeito de comissionamento: 

      - i. MATRIC-227 

      - ii. MATRIC-139 

      - iii. MATRIC-400 

      - iv. MATRIC-122 

      - v. MATRIC-387 

      - vi. MATRIC-78 

      - vii. MATRIC-10 

      - viii. MATRIC-356 

      - ix. MATRIC-405 

   - g. Somente para este mês, o % de comissionamento da marca 20 será aplicada em todos os cargos da marca 10 

   - h. Ajustar a data de demissão do funcionário MATRIC-62 para 15/09/25 

**4. Outubro de 2025** 

   - a. Funcionário MATRIC-179 pediu afastamento no dia 17/10/25 e retornou no dia 21/11/25 

   - b. Funcionário MATRIC-464 apresentou um atestado com afastamento do dia 06/10/25 até o dia 17/10/25 

   - c. Funcionário MATRIC-246 apresentou um atestado com afastamento do dia 06/10/25 até o dia 24/10/25 

   - d. Funcionário MATRIC-71 apresentou um atestado de licença maternidade a partir do dia 01/10/25 

   - e. Funcionário MATRIC-408 saiu de férias no período de 1/10/25 a 30/10/25 

   - f. Funcionário MATRIC-199 saiu de férias no período de 13/10/25 e retornou no dia 28/10/25 

   - g. Os funcionários da marca 30 tiveram um acréscimo de 0,5% no % de comissionamento já existente para todas as vendas realizadas no mês. Este bônus não se aplica aos cargos de gerente 

   - h. Os admitidos até o dia 10/10 no cargo 100 terão um bônus adicional de comissionamento de R$1.000 acrescido no valor final apurado de comissionamento 

**5. Novembro de 2025** 

   - a. Funcionário MATRIC-179 pediu afastamento no dia 17/10/25 e retorno no dia 21/11/25 

   - b. Funcionário MATRIC-5 apresentou um atestado com afastamento do dia 10/11/25 até o dia 12/12/25 

   - c. Funcionário MATRIC-71 apresentou um atestado de licença maternidade a partir do dia 01/10/25 

   - d. Funcionário MATRIC-581 saiu de férias no período de 10/11/25 a 24/11/25 

   - e. Funcionário MATRIC-52 saiu de férias no período de 24/11/25 e retornou no dia 13/12/25 

   - f. Todas as vendas no período de 24/11 a 30/11 terão um acréscimo no % de comissionamento de +1% (Black Friday). Valido para todas as marcas e para todos os cargos, com exceção dos gerentes (150). 

   - g. Para os Gerentes, todas as vendas do período de 24/11 a 30/11, terão um acréscimo de +0,5% no seu comissionamento. Valido para todas as marcas. 

6. Dezembro de 2025 

   - a. Funcionário MATRIC-188 pediu afastamento no dia 03/12/25 com retorno no dia 10/12/25 

   - b. Funcionário MATRIC-5 apresentou um atestado com afastamento do dia 10/11/25 até o dia 12/12/25 

   - c. Funcionário MATRIC-71 apresentou um atestado de licença maternidade a partir do dia 01/10/25 

   - d. Funcionário MATRIC-318 saiu de férias no período de 15/12/25 a 02/12/25 

   - e. Funcionário MATRIC-52 saiu de férias no período de 24/11/25 e retornou no dia 13/12/25 

   - f. Todas as vendas das marcas 40, 50 e 60 terão um acréscimo no % de comissionamento de +1%. Valido para todos os cargos, com exceção dos gerentes (150). 

   - g. Todas as vendas da marca 30 terão um acréscimo de +0,5% no seu comissionamento. Valido para todos os cargos, com exceção dos gerentes (150). 

   - h. Todas as vendas individuais das marcas 10 e 20, cuja o valor total da venda seja superior a R$40 mil, fará jus a um bônus individual conforme range abaixo: 40.000 até 50.000 – R$3.500 50.001 até 60.000 – R$4.000 > R$60.001            – R$4.500 

   - i. Para os Gerentes, todas as vendas total de loja apuradas, cujo valor total da venda por loja seja superior a R$120 mil, fará jus a um bônus fixo conforme range abaixo: 120.000 até 140.000 – R$5.000 140.001 até 160.000 – R$6.000 > R$160.001 – R$7.000 

