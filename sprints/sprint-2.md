<img width="1024" height="341" alt="image" src="https://github.com/user-attachments/assets/93b153b2-5274-4666-8df3-7aa32fa8736e" />

<br>
<br>

> Entrega programada: 25/10/2026 ✔️

## 🏁 O Desafio

Empresas lidam diariamente com regras de negócio dinâmicas — lançamento de novos produtos, mudanças de precificação, acordos comerciais e campanhas de comissionamento. O grande desafio operacional é 
que a base de conhecimento dessas regras frequentemente não é registrada de forma estruturada, resultando em perda de conhecimento tácito, inconsistência, conflito de regras e falta de rastreabilidade.

## 🫧 Nossa Solução

O **Synapse** é uma aplicação web inteligente criada para solucionar esse problema estrutural. O sistema permite que gestores definam novas regras de negócio através de **comandos de voz**, onde a 
Inteligência Artificial captura a intenção e a converte em código processável. Além disso, a aplicação simula o impacto financeiro da nova regra (comparando com o *baseline* da empresa), sugere adaptações 
em caso de inviabilidade orçamentária e garante total transparência e auditoria das decisões tomadas pelo modelo generativo.

## ⭐ MVP Sprint 2
O MVP da segunda sprint foca na automação inteligente da entrada de dados e na assistência ativa para a formulação de regras de negócio. As entregas centrais deste ciclo são:
* **Captura e Transcrição de Voz:** O sistema passa a aceitar a entrada de regras de negócio via áudio. Uma inteligência artificial transcreve a fala natural e a converte em código processável.
  A funcionalidade inclui validações de segurança que barram áudios inaudíveis, extremamente ruidosos ou com conversas fora do contexto de comissionamento e vendas.
* **Sugestões Automáticas de Adaptação:** Quando uma regra inserida se mostra financeiramente inviável ou incompatível, o sistema propõe ativamente um cenário alternativo de reformulação.
  O usuário mantém o controle final, podendo aceitar a sugestão, descartá-la para voltar à edição manual, ou receber um alerta crítico caso os parâmetros originais fujam completamente da política orçamentária da empresa.

## 🚀 Sprint 2 Backlog 
| Ranking | Prioridade | User Story (US) | Estimativa | Sprint |
| :---: | :---: | :--- | :---: | :---: |
| **03** | Alta | Como profissional de recursos humanos, quero a captura de voz e transcrição do conteúdo recebido, para que o início do fluxo no sistema seja prático. | 8 | 02 |
| **04** | Alta | Como profissional de recursos humanos, quero a sugestão automática de possível adaptação da regra de negócio*, para evitar inviabilidade por incompatibilidade dos parâmetros. | 8 | 02 |
> **Nota:** *Regra de negócio: Conjunto de parâmetros que definem as regras para o comissionamento após uma meta de vendas alcançada.

## ✅ Critérios de Aceitação

### US 03: Como profissional de recursos humanos, quero a captura de voz e transcrição do conteúdo recebido, para que o início do fluxo no sistema seja prático.
* **Cenário 1: Conversão de linguagem natural falada para código processável (Caminho Feliz)**
  * **Dado** que gravo um áudio com as condições desejadas da regra
  * **Quando** o sistema finalizar a escuta
  * **Então** a IA deve transcrever o conteúdo
  * **E** transformar a linguagem natural em um código que possa ser processado.
* **Cenário 2: Áudio inaudível, com ruído extremo ou mudo (Exceção)**
  * **Dado** que o usuário inicia a captura de voz
  * **Quando** o áudio recebido não contiver fala identificável ou estiver muito ruidoso
  * **Então** o sistema não deve tentar adivinhar ou gerar código vazio
  * **E** deve exibir uma mensagem de erro solicitando que o usuário grave novamente em um ambiente mais silencioso.
* **Cenário 3: Áudio fora do contexto de negócio (Restrição de Domínio)**
  * **Dado** que o modelo LLM recebe a transcrição do áudio
  * **Quando** o conteúdo transcrito não possuir intenção relacionada a regras de negócio (ex: conversa paralela)
  * **Então** o sistema deve interromper o fluxo
  * **E** informar ao usuário que não foi possível capturar o contexto ou especificar a intenção relacionada a comissionamentos ou vendas.

### US 04: Como profissional de recursos humanos, quero a sugestão automática de possível adaptação da regra de negócio*, para evitar inviabilidade por incompatibilidade dos parâmetros.
* **Cenário 1: Reformulação sugerida por ultrapassar o orçamento (Caminho Feliz)**
  * **Dado** que a regra original não cabe no orçamento
  * **Quando** a análise de incompatibilidade for concluída
  * **Então** o sistema deve propor um cenário que possa ser mais efetivo
  * **E** sugerir a reformulação da regra.
* **Cenário 2: Múltiplas variáveis incompatíveis sem solução óbvia (Restrição extrema)**
  * **Dado** que a regra proposta exige comissões absurdamente altas que inviabilizam qualquer adaptação leve
  * **Quando** o sistema tentar gerar a sugestão automática
  * **Então** a IA deve informar que os parâmetros estão criticamente fora da política da empresa
  * **E** solicitar que o usuário revise manualmente a meta de vendas e a porcentagem.
* **Cenário 3: Rejeição da sugestão pelo usuário (Fluxo alternativo)**
  * **Dado** que o sistema apresentou uma sugestão de adaptação
  * **Quando** o usuário julgar que a sugestão não atende à necessidade comercial
  * **Então** o sistema deve permitir que o usuário descarte a sugestão
  * **E** volte para a edição manual das regras e parâmetros.
 
## 🎯 DoR - Definition of Ready
- [x] Título claro, descrição definida e objetivo compreendido;
- [x] Critérios de aceitação escritos;
- [x] Regras de negócio claras;
- [x] Foi estimada pela equipe;
- [x] Sem dependências bloqueadoras;
- [x] Compreensão validada com o time;
- [x] Mockup disponível;
- [x] Os dados de treinamento estão disponíveis;

## 🎥 Demonstração Sprint 2
https://github.com/user-attachments/assets/5c50876b-64d8-44c6-9050-4d9dfb758745

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
