---
name: commit-and-comments
description: Convenções compartilhadas de commits, comentários de código e documentação do Synapse. Use ao criar ou revisar mensagens de commit, comentários, descrições de PR ou decidir se uma mudança exige atualização documental.
---

# Commits e documentação

Use esta skill ao escrever uma mensagem de commit, revisar comentários, preparar um PR ou decidir se uma mudança exige documentação ou atualização de ADR.

## Escopo do commit

- Um commit contém uma mudança lógica e relacionada.
- Não inclua correções, refatorações, dependências ou typos não relacionados à tarefa.
- Não crie commit ou branch sem solicitação explícita.
- Um serviço por PR. Só atravesse componentes quando uma mudança de contrato ou arquitetura exigir isso.

## Mensagem de commit

Use Conventional Commits em português brasileiro:

```text
<type>(<scope>): <resumo no imperativo>

- <tópico: o que mudou e por quê>

Review: <human|auto>
```

- `type`: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `style` ou `perf`.
- `scope`: módulo, componente ou área tocada; omita em mudanças de repositório inteiro.
- Resumo em minúsculas, no imperativo, sem ponto final e com aproximadamente 72 caracteres ou menos.
- Corpo opcional em bullets curtos. Explique decisões e motivos; não narre o diff linha a linha.
- `Review: human` significa que uma pessoa leu e aprovou o diff antes do commit.
- `Review: auto` significa que não houve revisão humana antes do commit.
- Não use o trailer `Co-authored-by:`.

Exemplo:

```text
feat(contracts): adiciona schema de resultado da simulação

- mantém o payload compartilhado entre API, codegen e worker

Review: human
```

## Comentários de código

Comentários explicam decisões não óbvias, nunca o funcionamento evidente do código.

Não use comentários para:

- repetir o que nomes e código já expressam;
- descrever estado temporal, como "por enquanto" ou "atualmente";
- registrar TODO sem responsável ou referência de tarefa;
- substituir nomes melhores ou uma documentação necessária.

Antes de escrever um comentário, pergunte: se o arquivo mudar amanhã de forma não relacionada, a justificativa continuará verdadeira? Se depender do estado atual, não escreva.

## Documentação e ADRs

Atualize a documentação ou um ADR quando a mudança alterar:

- contrato público ou mensagem compartilhada;
- decisão ou fronteira arquitetural;
- ownership de dados ou procedimento operacional;
- instalação, validação, CI/CD ou segurança do projeto.

Se a mudança contrariar um ADR, pare e reporte a incompatibilidade. Proponha a atualização da decisão antes de contorná-la em código.

## Verificação

Antes de finalizar:

- confira que o commit contém somente arquivos da tarefa;
- rode o gate do componente tocado;
- valide todos os consumidores quando houver mudança em `contracts/`;
- rode `git diff --check`;
- informe comandos executados, resultados e verificações não executadas.
