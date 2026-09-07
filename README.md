# 🧠 Synapse

> **Gerenciamento de Regras de Negócio com técnicas de engenharia de software assistida por IA**

Projeto desenvolvido para o 6º semestre de Análise e Desenvolvimento de Sistemas (ADS) da Fatec São José dos Campos, em parceria acadêmica com a **Dom Rock**.

---

## 📋 Sobre o Projeto

Empresas lidam diariamente com regras de negócio dinâmicas — lançamento de novos produtos, mudanças de precificação, acordos comerciais e campanhas de comissionamento. O grande desafio operacional é que a base de conhecimento dessas regras frequentemente não é registrada de forma estruturada, resultando em perda de conhecimento tácito, inconsistência, conflito de regras e falta de rastreabilidade.

O **Synapse** é uma aplicação web inteligente criada para solucionar esse problema estrutural. O sistema permite que gestores definam novas regras de negócio através de **comandos de voz**, onde a Inteligência Artificial captura a intenção e a converte em código processável. Além disso, a aplicação simula o impacto financeiro da nova regra (comparando com o *baseline* da empresa), sugere adaptações em caso de inviabilidade orçamentária e garante total transparência e auditoria das decisões tomadas pelo modelo generativo.

---

## 🚀 Product Backlog

| Ranking | Prioridade | User Story (US) | Estimativa | Sprint |
| :---: | :---: | :--- | :---: | :---: |
| **01** | Alta | Como gestor de negócios, quero a simulação dos futuros resultados da regra de negócio processada, para verificar sua viabilidade. | 13 | 01 |
| **02** | Alta | Como analista de RH, quero a captura de voz e transcrição do conteúdo recebido, para que o início do fluxo no sistema seja prático. | 8 | 02 |
| **03** | Alta | Como gerente comercial, quero a sugestão automática de possível adaptação da regra de negócio, para evitar inviabilidade por incompatibilidade dos parâmetros. | 8 | 02 |
| **04** | Média | Como auditor, quero o registro dos dados processados durante o fluxo principal de simulação, para averiguar as fontes dos dados obtidos ao final do processo. | 5 | 03 |
| **05** | Média | Como profissional de recursos humanos, quero que o sistema seja capaz de explicar todas as decisões tomadas durante o processo de simulação, para transparência dos resultados. | 8 | 03 |
| **06** | Média | Como analista de gente e gestão, quero um relatório após a finalização de cada processo, identificando a regra de negócio finalizada e sua simulação, para gravar meu histórico e facilitar o acesso posterior. | 3 | 01 |
| **07** | Baixa | Como profissional de recursos humanos, quero a validação dos dados obtidos por voz, a fim de confirmar se os parâmetros da regra de negócio foram recebidos e serão simulados de maneira correta. | 5 | 02 |

> **Nota:** *Regra de negócio* é definida como o conjunto de parâmetros que definem as regras para o comissionamento após uma meta de vendas alcançada.

---

## ✅ Critérios de Aceitação

### US 01: Simulação dos futuros resultados
* **Cenário 1: Comparação de simulação viável com o cenário atual**
  * **Dado** que o sistema recebeu e processou uma nova regra de negócio em formato de código
  * **Quando** eu solicitar a simulação dos futuros resultados
  * **Então** o sistema deve apurar o processo e calcular o comissionamento e lucros
  * **E** exibir a comparação com o cenário atual (baseline) permitindo novas simulações.
* **Cenário 2: Simulação resulta em inviabilidade financeira**
  * **Dado** que uma regra simulada gera um impacto negativo no lucro da empresa
  * **Quando** o sistema finalizar o cálculo dos futuros resultados
  * **Então** a interface deve alertar visualmente (ex: em vermelho) que a regra não cabe no orçamento
  * **E** bloquear a liberação direta para produção até que seja ajustada.

### US 02: Captura de voz e transcrição
* **Cenário 1: Conversão de linguagem natural falada para código processável**
  * **Dado** que gravo um áudio com as condições desejadas da regra
  * **Quando** o sistema finalizar a escuta
  * **Então** a IA deve transcrever o conteúdo
  * **E** transformar a linguagem natural em um código que possa ser processado.
* **Cenário 2: Áudio inaudível, com ruído extremo ou mudo**
  * **Dado** que o usuário inicia a captura de voz
  * **Quando** o áudio recebido não contiver fala identificável ou estiver muito ruidoso
  * **Então** o sistema não deve tentar adivinhar ou gerar código vazio
  * **E** deve exibir uma mensagem de erro solicitando que o usuário grave novamente em um ambiente mais silencioso.
* **Cenário 3: Áudio fora do contexto de negócio**
  * **Dado** que o modelo LLM recebe a transcrição do áudio
  * **Quando** o conteúdo transcrito não possuir intenção relacionada a regras de negócio (ex: conversa paralela)
  * **Então** o sistema deve interromper o fluxo
  * **E** informar ao usuário que não foi possível capturar o contexto ou especificar a intenção relacionada a comissionamentos ou vendas.

### US 03: Sugestão automática de adaptação
* **Cenário 1: Reformulação sugerida por ultrapassar o orçamento**
  * **Dado** que a regra original não cabe no orçamento
  * **Quando** a análise de incompatibilidade for concluída
  * **Então** o sistema deve propor um cenário que possa ser mais efetivo
  * **E** sugerir a reformulação da regra.
* **Cenário 2: Múltiplas variáveis incompatíveis sem solução óbvia**
  * **Dado** que a regra proposta exige comissões absurdamente altas que inviabilizam qualquer adaptação leve
  * **Quando** o sistema tentar gerar a sugestão automática
  * **Então** a IA deve informar que os parâmetros estão criticamente fora da política da empresa
  * **E** solicitar que o usuário revise manualmente a meta de vendas e a porcentagem.
* **Cenário 3: Rejeição da sugestão pelo usuário**
  * **Dado** que o sistema apresentou uma sugestão de adaptação
  * **Quando** o usuário julgar que a sugestão não atende à necessidade comercial
  * **Então** o sistema deve permitir que o usuário descarte a sugestão
  * **E** volte para a edição manual das regras e parâmetros.

### US 04: Auditoria e registro de dados processados
* **Cenário 1: Rastreabilidade das decisões**
  * **Dado** que uma simulação foi finalizada
  * **Quando** o usuário acessar a auditoria dos dados processados
  * **Então** o sistema deve explicar as decisões inferidas pela IA
  * **E** mostrar claramente como chegou na regra final.
* **Cenário 2: Perda de rastreabilidade na base de dados**
  * **Dado** que o sistema busca o cenário corrente (baseline) para comparação
  * **Quando** uma fonte de dados histórica estiver faltando ou a base de conhecimento não estiver registrada
  * **Então** o log de auditoria deve sinalizar explicitamente que ocorreu perda de rastreabilidade naquele ponto
  * **E** alertar que a simulação utilizou estimativas padrão em vez de dados históricos exatos.

### US 05: Relatório após finalização de cada processo
* **Cenário 1: Emissão de relatório e ações**
  * **Dado** que a simulação terminou com sucesso
  * **Quando** eu solicitar a finalização do processo
  * **Então** o sistema emite o relatório confrontando as regras
  * **E** me dá as opções de confirmar e liberar para produção, cancelar, salvar ou arquivar.
* **Cenário 2: Saída abrupta sem salvar (Prevenção de perda de dados)**
  * **Dado** que o relatório da simulação foi gerado na tela
  * **Quando** o usuário tentar fechar a aplicação (Frontend Vue.js) ou navegar para outra página sem escolher uma ação (arquivar, salvar ou liberar)
  * **Então** o sistema deve disparar um alerta de confirmação (ex: "Deseja sair sem salvar?")
  * **E** reter temporariamente o processamento no backend (SpringBoot) para evitar a perda do trabalho.

### US 06: Validação dos dados obtidos por voz
* **Cenário 1: Confirmação dos parâmetros extraídos**
  * **Dado** que o sistema realizou a transcrição por voz
  * **Quando** for finalizada a extração
  * **Então** a tela deve exibir os parâmetros (validade, canal, produto, equipe/funções, %)
  * **E** aguardar a validação e confirmação do usuário.
* **Cenário 2: Omissão de parâmetros obrigatórios pela fala**
  * **Dado** que a IA transcreveu a regra de negócio
  * **Quando** a transcrição falhar em identificar um parâmetro crucial (ex: não citou o canal ou o % de comissionamento)
  * **Então** o sistema não deve permitir que o fluxo siga para a simulação
  * **E** deve destacar os campos vazios obrigatórios, solicitando que o usuário os preencha manualmente na interface.
* **Cenário 3: Correção manual de alucinação ou erro da IA**
  * **Dado** que os parâmetros extraídos da voz estão na tela de validação
  * **Quando** o usuário notar que a IA interpretou "validade de 10 dias" no lugar do padrão da empresa "validade de 30 dias"
  * **Então** o sistema deve permitir que o usuário edite manualmente os valores inferidos
  * **E** deve registrar essa correção para auditoria futura.

---

## 🎯 DoR - Definition of Ready
- [x] Título claro, descrição definida e objetivo compreendido.
- [x] Critérios de aceitação escritos.
- [x] Regras de negócio claras.
- [x] Foi estimada pela equipe.
- [x] Sem dependências bloqueadoras.
- [x] Compreensão validada com o time.
- [x] Mockup disponível.
- [x] Os dados de treinamento estão disponíveis.

---

## 🏁 DoD - Definition of Done
- [ ] Atende aos critérios de aceitação.
- [ ] Atende aos requisitos funcionais.
- [ ] Code review feita e validada.
- [ ] Documentação de instalação finalizada.
- [ ] Código fonte disponível e executável.
- [ ] Teste de código realizado.
- [ ] Aprovado pela P.O.
- [ ] Vídeo dos incrementos da Sprint no repositório do github.

---

## 🛠️ Tecnologias e Arquitetura

O sistema atende aos requisitos técnicos e arquiteturais estabelecidos na Matriz de Competências do semestre:

**Frontend**
* **Vue.js**: Construção da interface de usuário operando como uma *Single Page Application* (SPA).

**Backend & Engenharia de Dados**
* **Spring Boot (Java)**: Desenvolvimento da API principal, regras de integração e arquitetura avançada.
* **Python**: Orquestração e microsserviços voltados para a Inteligência Artificial.

**Inteligência Artificial (Generativa e Orquestração)**
* **Modelos LLM Públicos (via API)**: Hugging Face, Gemini, Grok, Llama ou OpenAI.
* **Frameworks de IA**: Langchain, Langgraph, Llama Index.
* **IA na Codificação**: Uso de frameworks assistentes (Kiro, Cursor, Antigravity) durante o processo de desenvolvimento.

---

## 👥 Equipe

* Angelina Borroni Ferreira (PO)
* Pedro Garcia (Master)
* Maria Fernanda
* Pablo Rafael
* Julia Soares
* Matheus Germano
* Eduardo Ribeiro
* Wesley Gonçalves

**Instituição:** Fatec São José dos Campos - 6º ADS  
**Parceiro Acadêmico:** Dom Rock  
**Ponto Focal (Dom Rock):** André F. de Almeida  
**Professores Orientadores:** Claudio Lima (M2) e Walmir Duque (P2)
