<img width="1024" height="341" alt="image" src="https://github.com/user-attachments/assets/93b153b2-5274-4666-8df3-7aa32fa8736e" />

<br>
<br>

> Entrega: 27/09/2026 ⏳

## 🏁 O Desafio

Empresas lidam diariamente com regras de negócio dinâmicas — lançamento de novos produtos, mudanças de precificação, acordos comerciais e campanhas de comissionamento. O grande desafio operacional é 
que a base de conhecimento dessas regras frequentemente não é registrada de forma estruturada, resultando em perda de conhecimento tácito, inconsistência, conflito de regras e falta de rastreabilidade.

## 🫧 Nossa Solução

O **Synapse** é uma aplicação web inteligente criada para solucionar esse problema estrutural. O sistema permite que gestores definam novas regras de negócio através de **comandos de voz**, onde a 
Inteligência Artificial captura a intenção e a converte em código processável. Além disso, a aplicação simula o impacto financeiro da nova regra (comparando com o *baseline* da empresa), sugere adaptações 
em caso de inviabilidade orçamentária e garante total transparência e auditoria das decisões tomadas pelo modelo generativo.

## ⭐ MVP Sprint 1
O Produto Mínimo Viável (MVP) da primeira sprint foca na recepção inicial das novas regras de negócio e na validação de sua viabilidade orçamentária. As entregas que compõem este escopo inicial são:
* **Input de Dados:** Inserção das informações da regra de negócio via texto.
* **Simulação da Regra:** Cálculo do comissionamento gerados pela nova regra. O sistema compara os resultados com o cenário atual da empresa e emite alertas visuais caso a regra apresente inviabilidade financeira.
* **Telas de Histórico:** Geração de um relatório final após o processamento das regras. A interface permite salvar, arquivar, cancelar ou reprocessar os dados inseridos para evitar perdas e facilitar consultas futuras.

## 🚀 Sprint 1 Backlog 
| Ranking | Prioridade | User Story (US) | Estimativa | Sprint |
| :---: | :---: | :--- | :---: | :---: |
| **01** | Alta | Como profissional de recursos humanos, quero a simulação dos futuros resultados da regra de negócio* processada, para verificar sua viabilidade. | 13 | 01 |
| **02** | Baixa | Como profissional de recursos humanos, quero um relatório após a finalização de cada processo, identificando a regra de negócio finalizada e sua simulação, para gravar meu histórico e facilitar o acesso posterior. | 3 | 01 |
> **Nota:** *Regra de negócio: Conjunto de parâmetros que definem as regras para o comissionamento após uma meta de vendas alcançada.

## ✅ Critérios de Aceitação

### US 01: Como profissional de recursos humanos, quero a simulação dos futuros resultados da regra de negócio* processada, para verificar sua viabilidade.
* **Cenário 1: Comparação de simulação viável com o cenário atual (Caminho Feliz)**
  * **Dado** que o sistema recebeu e processou uma nova regra de negócio em formato de código
  * **Quando** eu solicitar a simulação dos futuros resultados
  * **Então** o sistema deve apurar o processo e calcular o comissionamento e lucros
  * **E** exibir a comparação com o cenário atual (baseline) permitindo novas simulações.
* **Cenário 2: Simulação resulta em inviabilidade financeira (Borda inferior)**
  * **Dado** que uma regra simulada gera um impacto negativo no lucro da empresa
  * **Quando** o sistema finalizar o cálculo dos futuros resultados
  * **Então** a interface deve alertar visualmente (ex: em vermelho) que a regra não cabe no orçamento
  * **E** bloquear a liberação direta para produção até que seja ajustada.

### US 07: Como profissional de recursos humanos, quero um relatório após a finalização de cada processo, identificando a regra de negócio finalizada e sua simulação, para gravar meu histórico e facilitar o acesso posterior.
* **Cenário 1: Emissão de relatório e ações (Caminho Feliz)**
  * **Dado** que a simulação terminou com sucesso
  * **Quando** eu solicitar a finalização do processo
  * **Então** o sistema emite o relatório confrontando as regras
  * **E** me dá as opções de cancelar, salvar ou arquivar.
* **Cenário 2: Saída abrupta sem salvar (Prevenção de perda de dados)**
  * **Dado** que o relatório da simulação foi gerado na tela
  * **Quando** o usuário tentar fechar a aplicação (Frontend Vue.js) ou navegar para outra página sem escolher uma ação (arquivar, salvar ou cancelar)
  * **Então** o sistema deve disparar um alerta de confirmação (ex: "Deseja sair sem salvar?")
  * **E** reter temporariamente o processamento no backend (SpringBoot) para evitar a perda do trabalho.
* **Cenário 3: Reutilização dos dados (Iniciar novo fluxo)**
  * **Dado** que um relatório foi arquivado
  * **Quando** o usuário escolher a opção de reprocessar aquela regra de negócio (ex: Um botão “Reprocessar” dentro do relatório) para verificar nova usabilidade, com base em novo orçamento
  * **Então** o sistema redirecionará o usuário para a página de confirmação de dados
  * **E** permitirá que o usuário mude os parâmetros desejados e faça uma nova simulação.
 
## 🎯 DoR - Definition of Ready
- [x] Título claro, descrição definida e objetivo compreendido;
- [x] Critérios de aceitação escritos;
- [x] Regras de negócio claras;
- [x] Foi estimada pela equipe;
- [x] Sem dependências bloqueadoras;
- [x] Compreensão validada com o time;
- [x] Mockup disponível;
- [x] Os dados de treinamento estão disponíveis;

## 🎥 Demonstração Sprint 1

https://github.com/user-attachments/assets/4031c0ad-1c23-4672-8da4-0ac0ffbc73ed

## 🏁 DoD - Definition of Done
- [x] Atende aos critérios de aceitação;
- [x] Atende aos requisitos funcionais;
- [x] Code review feita e validada;
- [x] Código fonte disponível e executável;
- [x] Teste de código realizado;
- [x] Teste realizado na visão do cliente pela P.O.;
- [x] Vídeo dos incrementos da Sprint no repositório do github.

<div align="right">
  <sub>by Titus Systems - A força por trás do seu sucesso! 🗡️🌿</sub>
</div>
