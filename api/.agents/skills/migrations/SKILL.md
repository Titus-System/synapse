---
name: migrations
description: Como o schema do Synapse evolui — changelog do Liquibase em Formatted SQL, numeração que é ordem de execução, rollback obrigatório, changeset publicado é imutável, e a regra do GRANT para tabela de outro serviço. Use ao criar ou alterar uma migration, ao adicionar tabela ou coluna, ou ao investigar por que um changeset não rodou.
---

# Migrations

A `api` é a dona do schema, inclusive das tabelas que `codegen` e `worker` escrevem. Nenhum outro componente cria ou altera estrutura, e nenhum ambiente recebe DDL na mão.

```
src/main/resources/db/changelog/
├── changelog.yaml          ← manifesto: só encadeia, nada de schema
└── changesets/
    ├── 000-cria-usuarios-de-banco.sql   ← os usuários dos serviços, antes de tudo
    ├── 001-cria-usuarios.sql            ← a tabela de usuários da aplicação
    ├── 002-cria-submissoes.sql
    └── ...
```

O changelog roda na subida da aplicação (`spring.liquibase.change-log`). A fonte canônica do modelo é [`modelo-dados.dbml`](../../../../docs/database/modelo-dados.dbml): o changeset implementa o que está lá, não o contrário.

## Acrescentar um changeset

1. Crie `changesets/NNN-<verbo>-<objeto>.sql` com o próximo número livre, três dígitos.
2. Abra com `-- liquibase formatted sql` e declare `-- changeset synapse:NNN-<verbo>-<objeto>`.
3. Escreva o DDL.
4. Feche com `-- rollback`.
5. Se a tabela é escrita por `codegen` ou `worker`, inclua o `GRANT` no mesmo changeset (ver abaixo).

```sql
-- liquibase formatted sql

-- changeset synapse:015-cria-exemplo
CREATE TABLE exemplo (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    job_id uuid NOT NULL,
    criado_em timestamptz NOT NULL,
    CONSTRAINT fk_exemplo_job_id FOREIGN KEY (job_id) REFERENCES jobs (id)
);

CREATE INDEX idx_exemplo_job_id ON exemplo (job_id);
-- rollback DROP TABLE exemplo;
```

O autor é sempre `synapse`, nunca o nome de quem escreveu: a identidade do changeset é `caminho::id::autor`, e amarrá-la a uma pessoa faz o mesmo changeset virar dois quando outra pessoa mexe no arquivo.

Nomes: `pk_`, `fk_<tabela>_<coluna>`, `idx_<tabela>_<colunas>`, `uq_<tabela>_<colunas>`.

## A numeração é a ordem de execução

`includeAll` ordena os arquivos alfabeticamente, então o prefixo numérico **é** a ordem em que o Postgres recebe o DDL. Um changeset que cria tabela com chave estrangeira precisa vir depois do que cria a tabela referenciada — numeração fora da ordem de dependência falha na subida, não em revisão.

## Rollback não é opcional

Todo changeset declara `-- rollback`. A escolha do Liquibase em vez do Flyway se paga exatamente aqui — no Flyway, rollback automático é recurso pago — e perde o sentido se a linha não for escrita.

Índice e constraint da própria tabela caem junto com ela: `DROP TABLE` basta, sem linha por índice.

## Changeset publicado é imutável

O Liquibase identifica cada changeset por `caminho::id::autor` e guarda o checksum do conteúdo em `databasechangelog`. Renomear o arquivo, mudar o id ou editar o SQL de um changeset **já aplicado** quebra o banco de quem já migrou: ou o Liquibase acusa checksum divergente, ou reaplica um DDL que já existe.

Corrigir algo que já foi para `develop` é um changeset novo, com o próximo número. Nunca uma edição no antigo.

## `GRANT` mora no changeset que cria a tabela

`codegen` e `worker` conectam com usuário próprio e só alcançam o que a permissão deixa. Um changeset que cria tabela escrita por um deles concede a permissão mínima ali mesmo, no mesmo arquivo.

Sem isso a tabela existe, o `INSERT` falha por permissão em runtime, e o erro aparece num serviço que não tem nada a ver com a migration que o causou.

```sql
GRANT SELECT ON codigos_gerados TO ${usuario_api};
GRANT SELECT, INSERT ON codigos_gerados TO ${usuario_codegen};
GRANT SELECT ON codigos_gerados TO ${usuario_worker};
```

**O nome do usuário vem por parâmetro, nunca literal.** Os três `${usuario_*}` são preenchidos por `spring.liquibase.parameters` no `application.yaml`, a partir do mesmo `.env` com que cada serviço conecta — um nome escrito à mão aqui divergiria em silêncio do usuário que o serviço usa. O usuário é criado em `000-cria-usuarios-de-banco.sql`, que roda antes de tudo; a senha não passa por aqui, porque o Liquibase expande o parâmetro **antes** de calcular o checksum e uma senha versionada quebraria a subida na primeira rotação. Pelo mesmo motivo, renomear um usuário depois de aplicado exige changeset novo.

`SELECT` acompanha `INSERT` para quem escreve: o id nasce de `DEFAULT uuidv7()` no servidor, e `INSERT ... RETURNING id` exige `SELECT` na coluna.

Quem escreve o quê está na [seção 6.2 da arquitetura](../../../../docs/ARCHITECTURE.md); a integridade referencial continua funcionando mesmo sem permissão na tabela referenciada, porque no Postgres a checagem de FK roda com os privilégios do dono da tabela.

Nada disso vale para o dono do schema: superusuário no Postgres ignora a checagem de privilégio inteira, e é por configuração, não pelo banco, que nenhum serviço opera com ele.

`PermissoesDeBancoTests` prova a negativa de ponta a ponta, afirmando o SQLState `42501`. Um `GRANT` a mais escapa do teste; um a menos, não.

## Armadilhas

**A raiz é YAML e isso é deliberado.** `include`/`includeAll` num changelog raiz em Formatted SQL é recurso pago (Liquibase Secure 4.28+), e a decisão por Liquibase se sustenta no core open source. O manifesto não descreve schema — só encadeia arquivos. Todo DDL vive em `.sql` puro.

**`uuidv7()` exige Postgres 18.** É função nativa, sem extensão. A PK nasce com `DEFAULT uuidv7()`, mas o default só vale quando o `INSERT` omite a coluna: id fornecido pela aplicação entra como veio, inclusive se for v4. Não existe `CHECK` de versão — v7 é convenção sustentada pelo default, não invariante imposta.

**Enum do DBML não é `CHECK`.** Os valores anotados como `a | b | c` são vocabulário documentado. A coluna é `text`, sem `CHECK`, sem tabela de domínio e sem o tipo `ENUM` nativo; quem valida é o código de cada stack, com `contracts/` como autoridade compartilhada.

**O DBML não expressa índice parcial nem direção de ordenação.** Onde a migration precisa de um dos dois, está anotado no note do índice — e é responsabilidade do changeset implementar.

**As tabelas de checkpoint do LangGraph não são nossas.** A própria biblioteca as cria e migra, e só o `codegen` as acessa. Nenhum changeset as toca.

## Verificação

```bash
make test    # MigrationTests sobe um Postgres 18 real e confere aplicação,
             # idempotência da segunda subida, rollback e a versão do uuid;
             # PermissoesDeBancoTests conecta com cada usuário e confere o que
             # ele alcança e o que o banco recusa
```

O teste é ignorado quando não há Docker na máquina. Ele não substitui subir a aplicação contra o Postgres do compose antes de abrir o PR.

## Referências

- Fonte canônica do modelo: [`modelo-dados.dbml`](../../../../docs/database/modelo-dados.dbml)
- Decisões de persistência: [arquitetura, seção 5](../../../../docs/ARCHITECTURE.md)
- Formato de cada coluna `jsonb`: [`contracts/domain/`](../../../../contracts/domain/)
