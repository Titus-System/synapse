# AGENTS.md

## As convenções moram em `.agents/skills/`

Toda convenção deste repositório é um skill. Leia o que cobre o que você vai tocar, e quando uma regra mudar, mude-a no skill dela — nada aqui é documentado duas vezes.

| Skill | Leia antes de |
| --- | --- |
| [`configuration`](.agents/skills/configuration/SKILL.md) | Acrescentar uma configuração, ler uma existente num componente, ou investigar por que um valor não chegou. |
| [`logging`](.agents/skills/logging/SKILL.md) | Escrever ou mudar uma chamada de log. |
| [`metrics`](.agents/skills/metrics/SKILL.md) | Declarar uma métrica, adicionar uma tag, ou nomear qualquer uma das duas. |
| [`code-quality`](.agents/skills/code-quality/SKILL.md) | Commitar, escrever um método que pode não ter resposta, ou escrever um comentário. |
| [`architecture`](.agents/skills/architecture/SKILL.md) | Criar um domínio, decidir onde uma classe mora, ou fazer uma fatia enxergar outra. |

O envelope de log é contrato entre serviços e está especificado no repositório `agents`, em `.agents/skills/observability/SKILL.md`. Mudar um campo de topo aqui exige mudar os outros serviços junto.

## O portão

```bash
make check     # formato + análise estática + testes
```

```bash
make fmt       # reformata no lugar
make lint      # formato + Error Prone + NullAway
make test      # só os testes
make run       # sobe a aplicação
```

- **spring-javaformat** cuida da formatação. `make fmt` antes de commitar.
- **Error Prone** e **NullAway** são plugins do `javac`: rodam na compilação e quebram o build, não avisam.
- O projeto exige **Java 21**. O Makefile aponta o `JAVA_HOME` para um JDK 21 local quando a variável não está definida.
- Nenhuma dessas três aparece na IDE — o VSCode compila com outro compilador. O portão é o build.

## Segurança

- **Job e evento de outbox, sempre na mesma transação.** Toda escrita que produz um evento de outbox ocorre dentro do mesmo `@Transactional` que grava a entidade de job/estado que o originou. Publicar o evento num listener `AFTER_COMMIT`, num `@Async` sem propagação de transação, ou em qualquer caminho que possa confirmar um sem o outro, é rejeitado em revisão.
- **Nenhuma escrita em tabela de artefato de outro serviço.** A api nunca faz `INSERT`/`UPDATE`/`DELETE` em tabela que armazena artefatos produzidos por `codegen` ou `worker` (código gerado, resultado de simulação). Quando precisa do dado, lê pela referência publicada no evento; nunca grava direto na tabela alheia.
- **Migration só nasce aqui.** Toda migration do banco do Synapse é adicionada em `api/`. Se `codegen` ou `worker` precisam de tabela ou coluna nova, a migration inclui o `GRANT` de permissão mínima para aquele serviço; nenhum outro componente cria ou altera schema.
- **Evite herança para reaproveitar comportamento.** Uma superclasse abstrata para compartilhar lógica entre fatias (`commissioning`, `sales`, `approval`) ou entre camadas da mesma fatia é rejeitada em revisão, a menos que justificada explicitamente; prefira composição ou um método de apoio dentro do próprio pacote.
- **Consumidor de fila é idempotente.** Uma redelivery do RabbitMQ (a mesma mensagem entregue de novo) nunca cria um segundo job nem duplica efeito financeiro; o consumidor deduplica pelo identificador da mensagem/evento antes de processar.
- **Nenhuma query monta filtro por concatenação de string com dado de usuário.** Toda consulta usa parâmetro bind do Spring Data/JPA (`@Param`, `Pageable`, Criteria API); concatenar texto de proposta, transcrição ou qualquer entrada de usuário para formar uma query é rejeitado em revisão.
- **Resposta de erro não expõe detalhe interno.** Um `@ExceptionHandler`/`ControllerAdvice` nunca devolve stack trace, mensagem de exceção do driver JDBC ou nome de tabela/coluna no corpo da resposta; a mensagem exposta ao frontend é uma que o domínio decidiu expor.
- **Toda leitura ou escrita de job confere posse.** Um endpoint que recebe um `jobId` (ou qualquer identificador de recurso) verifica que o solicitante autenticado é dono do recurso, ou tem papel que autoriza o acesso, antes de retornar ou alterar dado — nunca confia só na autenticação.
- **Nenhum segredo real em arquivo versionado.** `.env.example` só tem placeholder; uma credencial, chave ou connection string real nunca entra num arquivo rastreado pelo git nem é logada, mesmo em erro.
- **Observabilidade**: o envelope de log é o contrato em [`../contracts/observability/`](../contracts/observability/README.md); não redeclare campos aqui.

Verificação: `make check` (ver "O portão", acima).
