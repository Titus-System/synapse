# Arquitetura do Synapse

Arquitetura orientada a eventos, com serviços independentes e comunicação assíncrona via mensageria.

```mermaid
flowchart TB
    U([Usuário]) --> FE

    subgraph Acesso
        direction LR
        FE["Frontend<br/>Vue"] --> GW["Gateway"]
        KC["Keycloak<br/>login e papéis"]
    end

    GW --> API

    subgraph Servicos["Serviços"]
        direction LR
        API["API<br/>Spring Boot"]
        CG["Codegen<br/>LangGraph"]
        WK["Worker<br/>Python"]
    end

    Servicos <--> MQ{{"RabbitMQ<br/>mensagens entre serviços"}}
    Servicos --> DB[("PostgreSQL<br/>jobs, regras, resultados, auditoria")]

    CG --> LLM["Modelo de IA"]
    WK --> SB[["Sandbox Docker<br/>execução isolada"]]

    Servicos -.-> AL["Grafana Alloy"] --> GF["Grafana Cloud<br/>Loki e Prometheus"]

    FE -.-> KC
    API -.-> KC
```

## Como funciona

1. **Envio.** O usuário descreve a regra no frontend; a API registra o job.
2. **Interpretação.** O codegen entende a intenção, extrai os parâmetros da regra e gera o código correspondente com apoio de IA.
3. **Simulação.** O worker executa o código em um container isolado, sobre os dados históricos reais, e compara o resultado com o baseline e com o orçamento.
4. **Explicação.** O resultado é explicado e apresentado ao usuário, que decide confirmar, cancelar, salvar ou arquivar.

## Tecnologias utilizadas

<ul>
  <li>
      <img alt="Vue" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/vuejs/vuejs-original.svg"> 
      <img alt="TypeScript" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/typescript/typescript-original.svg"> <img alt="Vite" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/vitejs/vitejs-original.svg"> <b>Vue, TypeScript e Vite:</b> interface web para envio de regras, acompanhamento de jobs e visualização de resultados.</li>
  <li><img alt="Java" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/java/java-original.svg"> <img alt="Spring" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/spring/spring-original.svg"> <b>Java 21 e Spring Boot:</b> API REST, estado dos jobs, atualizações em tempo real e migrations.</li>
  <li><img alt="Python" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/python/python-original.svg"> <img alt="LangGraph" height="24" width="24" src="https://cdn.simpleicons.org/langchain"> <b>Python e LangGraph:</b> interpretação das propostas, geração e explicação das regras.</li>
  <li><img alt="Docker" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/docker/docker-original.svg"> <b>Docker:</b> sandbox efêmero e isolado para executar as regras geradas.</li>
  <li><img alt="RabbitMQ" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/rabbitmq/rabbitmq-original.svg"> <b>RabbitMQ:</b> comunicação assíncrona entre os serviços.</li>
  <li><img alt="PostgreSQL" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/postgresql/postgresql-original.svg"> <b>PostgreSQL:</b> armazenamento de jobs, auditoria, regras e artefatos.</li>
  <li><img alt="Keycloak" height="24" width="24" src="https://cdn.simpleicons.org/keycloak"> <b>Keycloak:</b> login e controle de acesso por papel (profissional de RH e auditor).</li>
  <li><img alt="OpenTelemetry" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/opentelemetry/opentelemetry-original.svg"><img alt="Grafana" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/grafana/grafana-original.svg"><img alt="Prometheus" height="24" width="24" src="https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons/prometheus/prometheus-original.svg"> <b>Observabilidade: Opentelemetry, Grafana, Loki, Prometheus</b> </li>
  
  <
</ul>
