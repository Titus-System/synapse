---
name: architecture
description: Decisões arquiteturais e fronteiras entre os componentes do Synapse. Use ao alterar ownership de dados, comunicação entre serviços, responsabilidades ou uma decisão registrada em ADR.
---

# Decisão arquitetural

Use esta skill quando uma mudança criar ou mover uma fronteira entre componentes, alterar o canal de comunicação, mudar ownership de dados ou contrariar um ADR.

## Roteamento mínimo

1. Identifique a decisão local que controla o comportamento.
2. Leia somente o ADR correspondente em `docs/adrs/`.
3. Leia a seção relacionada de `docs/ARCHITECTURE.md`; não leia o documento inteiro por padrão.
4. Consulte o componente vizinho apenas se a decisão afetar seu contrato ou sua responsabilidade.

## Invariantes

- `frontend`, `api`, `codegen` e `worker` são componentes independentes no monorepo.
- Comunicação de negócio entre serviços ocorre somente por RabbitMQ.
- `api` é dona do estado do job, das transições, da auditoria e das migrations.
- Cada serviço usa seu usuário próprio no PostgreSQL e grava somente o que lhe pertence.
- `contracts/` é insumo de build, não dependência de runtime.
- O `worker` é o único componente autorizado a executar código gerado, sempre em sandbox isolado.
- O frontend não implementa regras de negócio nem calcula valores exibidos.

## Quando a decisão mudou

Se a alteração contradiz um ADR, não esconda a incompatibilidade em código ou configuração. Registre a alternativa, o impacto e a decisão necessária antes de implementar uma nova fronteira. Atualize o ADR quando a decisão for aprovada.

## Validação

- Verifique que o componente dono continua sendo o único responsável pelo estado ou artefato.
- Verifique os contratos e permissões dos componentes afetados.
- Valide primeiro cada componente isoladamente e depois o fluxo atravessado, quando houver ambiente para isso.
- Documente no encerramento qual decisão arquitetural foi preservada ou alterada.
