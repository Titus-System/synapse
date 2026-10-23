<img width="1024" height="341" alt="image" src="https://github.com/user-attachments/assets/93b153b2-5274-4666-8df3-7aa32fa8736e" />

<br>
<br>

> Entrega programada: 22/11/2026 ⏳

## 🏁 O Desafio

Empresas lidam diariamente com regras de negócio dinâmicas — lançamento de novos produtos, mudanças de precificação, acordos comerciais e campanhas de comissionamento. O grande desafio operacional é 
que a base de conhecimento dessas regras frequentemente não é registrada de forma estruturada, resultando em perda de conhecimento tácito, inconsistência, conflito de regras e falta de rastreabilidade.

## 🫧 Nossa Solução

O **Synapse** é uma aplicação web inteligente criada para solucionar esse problema estrutural. O sistema permite que gestores definam novas regras de negócio através de **comandos de voz**, onde a 
Inteligência Artificial captura a intenção e a converte em código processável. Além disso, a aplicação simula o impacto financeiro da nova regra (comparando com o *baseline* da empresa), sugere adaptações 
em caso de inviabilidade orçamentária e garante total transparência e auditoria das decisões tomadas pelo modelo generativo.

## ⭐ MVP Sprint 3
O MVP da terceira sprint foca em auditoria, transparência das decisões da inteligência artificial e controle humano sobre a entrada de dados. As entregas centrais deste ciclo são:
* **Registro de Dados e Auditoria:** O sistema passa a gravar logs estruturados do fluxo de simulação, garantindo a rastreabilidade das fontes de dados, IDs únicos e versões das regras aplicadas.
  O modelo inclui contingência de retenção temporária de logs em caso de falhas de conexão.
* **Explicabilidade das Decisões da IA:**Armazenamento das justificativas e do raciocínio lógico utilizados pelo modelo generativo durante os cálculos. O sistema passa a registrar alertas (flags) de
  "baixa rastreabilidade" caso a IA retorne apenas resultados matemáticos sem a devida explicação.
* **Validação de Parâmetros Extraídos por Voz:**Implementação de uma interface de confirmação para o profissional de RH revisar os parâmetros capturados (validade, canal, produto, equipe, porcentagem).
  A funcionalidade bloqueia a simulação caso faltem dados obrigatórios e permite a correção manual de eventuais alucinações ou interpretações incorretas da IA.

## 🚀 Sprint 3 Backlog 
| Ranking | Prioridade | User Story (US) | Estimativa | Sprint |
| :---: | :---: | :--- | :---: | :---: |
| **05** | Média | Como auditor, quero o registro dos dados processados durante o fluxo principal de simulação, para averiguar as fontes dos dados obtidos ao final do processo. | 5 | 03 |
| **06** | Média | Como auditor, quero que o sistema seja capaz de explicar todas as decisões tomadas durante o processo de simulação, para transparência dos resultados. | 8 | 03 |
| **07** | Baixa | Como profissional de recursos humanos, quero a validação dos dados obtidos por voz, a fim de confirmar se os parâmetros da regra de negócio* foram recebidos e serão simulados de maneira correta. | 5 | 03 |
> **Nota:** *Regra de negócio: Conjunto de parâmetros que definem as regras para o comissionamento após uma meta de vendas alcançada.

## ✅ Critérios de Aceitação

### US 04: Como auditor, quero o registro dos dados processados durante o fluxo principal de simulação, para averiguar as fontes dos dados obtidos ao final do processo.
* **Cenário 1: Gravação bem-sucedida do log de auditoria no sistema (Caminho Feliz)**
  * **Dado** que o motor de simulação finaliza o processamento de uma regra de negócio
  * **Quando** os dados de resultado forem consolidados
  * **Então** o sistema deve gravar automaticamente no banco de dados (ou serviço de logs) um registro estruturado (ex: JSON) do fluxo principal
  * **E** esse registro deve conter obrigatoriamente a origem/fonte de cada dado processado para que possa ser averiguado via banco ou API por um auditor.
* **Cenário 2: Falha na comunicação com o serviço de persistência de logs (Exceção)**
  * **Dado** que o backend tenta gravar o registro de auditoria da simulação
  * **Quando** ocorrer uma falha de conexão com o banco de dados ou serviço de log primário
  * **Então** o sistema não deve interromper a simulação para o usuário
  * **E** deve reter o log temporariamente em memória ou em um arquivo local seguro até que a conexão seja restabelecida, garantindo que o registro não se perca.
* **Cenário 3: Integridade e amarração dos dados salvos (Restrição)**
  * **Dado** que uma simulação consulta múltiplas fontes de dados
  * **Quando** o sistema estruturar o pacote (payload) de logs para gravação
  * **Então** o sistema deve garantir que o registro inclua um Identificador Único (ID da simulação), um timestamp (data e hora) e a versão exata da regra aplicada
  * **E** vincular essas informações de forma inseparável às fontes obtidas ao final do processo.

### US 05: Como auditor, quero que o sistema seja capaz de explicar todas as decisões tomadas durante o processo de simulação, para transparência dos resultados.
* **Cenário 1: Persistência do raciocínio e justificativas da IA (Caminho Feliz)**
  * **Dado** que o modelo de IA (LLM) processa a regra de negócio e gera os resultados da simulação
  * **Quando** o cálculo for finalizado pelo backend
  * **Então** o sistema deve armazenar um artefato de texto (ou estrutura de dados) que contenha a explicação lógica e as decisões tomadas pela IA
  * **E** essa explicação deve ficar atrelada ao registro da simulação no sistema, disponível para extração e conferência técnica pela equipe de RH visando a transparência.
* **Cenário 2: Retorno de inferência da IA sem justificativa detalhada (Exceção/Borda)**
  * **Dado** que o sistema recebe o retorno da API do modelo de IA (ex: Hugging Face, Gemini, OpenAI)
  * **Quando** o modelo retornar apenas o resultado matemático, falhando em fornecer a explicação das decisões tomadas
  * **Então** o sistema deve registrar o resultado no banco
  * **E** deve gravar uma flag (alerta) no banco de dados indicando que aquela simulação específica possui "baixa rastreabilidade de explicabilidade", sinalizando a falha para auditorias futuras.

### US 06: Como profissional de recursos humanos, quero a validação dos dados obtidos por voz, a fim de confirmar se os parâmetros da regra de negócio* foram recebidos e serão simulados de maneira correta.
* **Cenário 1: Confirmação dos parâmetros extraídos (Caminho Feliz)**
  * **Dado** que o sistema realizou a transcrição por voz
  * **Quando** for finalizada a extração
  * **Então** a tela deve exibir os parâmetros (validade, canal, produto, equipe/funções, %)
  * **E** aguardar a validação e confirmação do usuário.
* **Cenário 2: Omissão de parâmetros obrigatórios pela fala (Exceção/Restrição)**
  * **Dado** que a IA transcreveu a regra de negócio
  * **Quando** a transcrição falhar em identificar um parâmetro crucial (ex: não citou o canal ou o % de comissionamento)
  * **Então** o sistema não deve permitir que o fluxo siga para a simulação
  * **E** deve destacar os campos vazios obrigatórios, solicitando que o usuário os preencha manualmente na interface.
* **Cenário 3: Correção manual de alucinação ou erro da IA (Edição de borda)**
  * **Dado** que os parâmetros extraídos da voz estão na tela de validação
  * **Quando** o usuário notar que a IA interpretou "validade de 10 dias" no lugar do padrão da empresa "validade de 30 dias"
  * **Então** o sistema deve permitir que o usuário edite manualmente os valores inferidos
  * **E** deve registrar essa correção para auditoria futura.
 
## 🎯 DoR - Definition of Ready
- [ ] Título claro, descrição definida e objetivo compreendido;
- [ ] Critérios de aceitação escritos;
- [ ] Regras de negócio claras;
- [ ] Foi estimada pela equipe;
- [ ] Sem dependências bloqueadoras;
- [ ] Compreensão validada com o time;
- [ ] Mockup disponível;
- [ ] Os dados de treinamento estão disponíveis;

## 🎥 Demonstração Sprint 3

[Vídeo será inserido aqui]

## 🏁 DoD - Definition of Done
- [ ] Atende aos critérios de aceitação;
- [ ] Atende aos requisitos funcionais;
- [ ] Code review feita e validada;
- [ ] Código fonte disponível e executável;
- [ ] Teste de código realizado;
- [ ] Teste realizado na visão do cliente pela P.O.;
- [ ] Vídeo dos incrementos da Sprint no repositório do github.

<div align="right">
  <sub>by Titus Systems - A força por trás do seu sucesso! 🗡️🌿</sub>
</div>
