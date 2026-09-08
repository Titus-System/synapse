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
