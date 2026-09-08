---
name: contract-change
description: Evolução compatível dos contratos JSON Schema, exemplos e mensagens compartilhadas entre os componentes do Synapse. Use ao alterar schemas, eventos, comandos ou payloads consumidos por mais de um serviço.
---

# Mudança de contrato

Use esta skill quando uma alteração modificar um schema em `contracts/`, um exemplo válido ou o formato de uma mensagem consumida por mais de um componente.

## Autorização obrigatória

Antes de editar, pare e peça autorização explícita ao usuário. O pedido deve informar:

- contrato, exemplo ou payload que será alterado;
- produtores e consumidores afetados;
- compatibilidade esperada e risco de quebra;
- arquivos que serão tocados;
- validações necessárias.

Não altere o schema, o produtor ou os consumidores antes da autorização.

## Roteamento

1. Leia somente o schema e os exemplos diretamente envolvidos.
2. Identifique produtor e todos os consumidores no catálogo de eventos ou na busca do repositório.
3. Confira o ADR ou a seção de arquitetura apenas se a mudança alterar compatibilidade, ownership ou fronteira entre serviços.
4. Leia as instruções locais dos componentes que realmente serão tocados.

## Regras

- Contratos são JSON Schema neutros em relação às stacks.
- Evolua eventos de forma aditiva: campos novos começam opcionais.
- Não remova nem renomeie campos existentes sem decisão arquitetural explícita.
- Não use `additionalProperties: false` em eventos.
- Ausência e `null` não são equivalentes; campo opcional ausente é o padrão para compatibilidade.
- Eventos carregam referências, não prompts, transcrições, código gerado, datasets ou resultados completos.
- Cada schema alterado mantém pelo menos um exemplo válido atualizado.
- DTOs e modelos pertencem aos consumidores e não devem importar código de `contracts/` em runtime.

## Validação

- Valide a sintaxe e a estrutura do schema.
- Valide os exemplos contra os schemas.
- Rode os testes dos produtores e consumidores afetados.
- Rode `git diff --check`.
- Informe no encerramento quais consumidores foram verificados e quais não puderam ser executados.

Não faça uma refatoração ampla dos consumidores para acompanhar uma pequena mudança de contrato. Separe mudanças de comportamento não necessárias para compatibilidade.
