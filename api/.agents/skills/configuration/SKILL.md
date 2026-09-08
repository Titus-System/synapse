---
name: configuration
description: Como a configuração entra e circula nesta API — o `.env` com entrada única, o bloco `app` do application.yaml, o `AppProperties` injetado por DI, e a proibição de ler variável de ambiente em qualquer outro lugar. Use ao acrescentar uma configuração, ao ler uma existente num componente, ou ao investigar por que um valor não chegou.
---

# Configuração

Uma variável de ambiente é lida **em um lugar só** e daí em diante todo mundo consome o objeto. Nenhum ponto do código chama `System.getenv`.

```
.env  +  variáveis do processo
            │
            ▼
  application.yaml, bloco `app:`     ← único lugar que escreve ${VARIÁVEL}
            │
   ┌────────┼──────────────┐
   ▼        ▼              ▼
resto do   logback-      AppProperties
YAML       spring.xml    (injetado)
```

## Acrescentar uma configuração

1. Declare no bloco `app:` de `application.yaml`, com default:
   ```yaml
   app:
     rabbitmq:
       url: ${RABBITMQ_URL:amqp://localhost:5672}
   ```
2. Documente a variável no `.env.example`.
3. Acrescente o componente ao record correspondente em `AppProperties`, com a anotação de validação que couber.

O Javadoc `@param` de cada componente não é enfeite: o `spring-boot-configuration-processor` o transforma na descrição que a IDE mostra ao completar `app.*` dentro do `application.yaml`. Componente sem `@param` aparece sem descrição.

## Consumir

Injete. É um bean como qualquer outro:

```java
@Service
class JobPublisher {

    private final AppProperties properties;

    JobPublisher(AppProperties properties) {
        this.properties = properties;
    }

    void publish() {
        connect(this.properties.postgres().jdbcUrl());
    }
}
```

Nunca `@Value("${...}")` e nunca `environment.getProperty(...)`: ambos espalham a chave em string pelo código e furam o ponto único.

**A única exceção** é o `JsonLogFormatter`, que é instanciado pelo sistema de logging antes de o contexto Spring existir e por isso não tem bean para injetar. Ele monta o `AppProperties` na mão, a partir do `Environment`, no seu método privado `bind`. Não copie esse padrão para código novo.

`NoDirectEnvironmentAccessTests` varre `src/main/java` e quebra o build se `System.getenv` reaparecer.

## Precedência

Verificada, não suposta:

```
variável de ambiente real   ← ganha   (o que Docker/k8s injeta)
        ↑
      .env                            (o arquivo local)
        ↑
default do application.yaml ← perde   (o :development de ${ENVIRONMENT:development})
```

Em produção o runtime sobrepõe qualquer arquivo; na máquina do desenvolvedor o `.env` preenche o que falta.

## Armadilhas

**`LOG_LEVEL` usa o vocabulário do Logback**, não o do Python: `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL`, `OFF`. `WARNING` e `CRITICAL` derrubam a aplicação na subida **com zero bytes de saída** — quem falha é a inicialização do log, então não sobra nada para reportar o erro.

**`file:.env` é relativo ao diretório de trabalho do processo**, não ao jar. Rodar `java -jar` de outro diretório não acha o arquivo, e como o import é `optional:` isso não gera erro nenhum: a aplicação sobe silenciosamente com todos os defaults.

**O `.env` local vaza para os testes.** `mvnw test` carrega o `.env` do desenvolvedor no contexto dos testes. Hoje passa porque nenhum teste afirma nada sobre esses valores. O `.env.test` existe mas ainda não está ligado a nada.

## Referências

- Entrada e mapeamento: [`application.yaml`](../../../src/main/resources/application.yaml)
- O objeto: [`AppProperties`](../../../src/main/java/synapse/api/core/config/AppProperties.java)
