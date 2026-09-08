---
name: code-quality
description: O portão de qualidade desta API — o que o javac, o Error Prone e o NullAway verificam, a política de nunca retornar null, formatação com spring-javaformat, e a regra de comentários. Use antes de commitar, ao escrever um método que pode não ter resposta, ao escrever um comentário, ou ao investigar uma falha de compilação vinda dessas ferramentas.
---

# Qualidade de código

```bash
make fmt      # reformata no lugar
make check    # o portão: formato + análise estática + testes
```

`make lint` valida formato e compila; é a **compilação** que dispara Error Prone e NullAway, porque eles são plugins do `javac`, não ferramentas separadas.

## As três camadas

| Camada | Ferramenta | Pega |
| --- | --- | --- |
| Tipos | o próprio `javac` | incompatibilidade, aridade, método inexistente, exaustividade de `switch` sobre `sealed` |
| Bugs prováveis | Error Prone (~500 checks) | `ArrayEquals`, `CollectionIncompatibleType`, `SelfAssignment` e afins |
| Nulidade | NullAway | desreferência e retorno de `@Nullable` onde se espera não-nulo |

Nada disso é aviso: os três quebram o build.

O NullAway está restrito a `synapse.api` (`AnnotatedPackages`). Os pacotes do Spring ficam de fora por ora, embora o Boot 4 seja 100% `@NullMarked` e pudesse ser incluído — a decisão foi começar pelo nosso código e medir o atrito antes.

O `.mvn/jvm.config` existe porque o Error Prone acessa internos do `javac` que o JDK 17+ fechou. Sem aqueles `--add-exports` a compilação estoura com `IllegalAccessError`.

## Nunca retorne null

O `javac` não tem verificação de nulidade: `talvez().length()` compila e explode em produção. A política, em ordem de preferência:

1. **Valor vazio** — `Map.of()`, `List.of()`, `""`, ou um default nomeado como `"unknown"`. Resolve a maioria dos casos e não obriga ninguém a checar nada.
2. **`@Nullable`** (de `org.jspecify.annotations`) — quando a ausência é o próprio sinal e não existe vazio universal, como num método genérico. O NullAway então **obriga** quem chama a tratar.
3. **Exceção** — só quando a ausência é erro: bug ou condição da qual não dá para seguir. Ausência normal e esperada não é isso.

`Optional` não entra nessa lista para código interno: aloca por chamada, e por convenção não se usa em campo nem em parâmetro. Cabe em API pública que pode legitimamente não ter resposta.

Anote a **produção**, nunca silencie o teste. Um teste que passa `null` e o NullAway reclama normalmente revelou que a assinatura aceita `null` por design e nunca declarou isso.

## Formatação

`spring-javaformat` — tabs, e imports com o bloco `org.springframework` separado. É o estilo do próprio Spring.

Não force quebras de linha com truques (um `//` no fim da linha, por exemplo): o formatador briga com eles e produz saída pior do que se você deixar ele decidir.

O VSCode não aplica esse formato ao salvar sozinho, nem mostra Error Prone ou NullAway sublinhados — a IDE compila com outro compilador. Os três são portão de build, não de edição.

## Comentários

**Breves, e só quando estritamente necessários.**

Um comentário existe para dizer o que o código não consegue: um modo de falha silencioso, uma restrição de ordem não óbvia, o motivo de uma exceção ser engolida. Nunca para repetir o que a linha seguinte já diz.

A razão de ser de uma decisão vai no SKILL.md do assunto, não no código — este repositório documenta convenção em um lugar só.

Quando um comentário fica longo, quase sempre o problema é outro: nome ruim, ou lógica no lugar errado. Prefira renomear a explicar.

## Referências

- Alvos e JDK: [`Makefile`](../../../Makefile)
- Plugins e escopo do NullAway: [`pom.xml`](../../../pom.xml)
