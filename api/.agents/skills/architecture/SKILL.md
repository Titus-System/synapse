---
name: architecture
description: Como o código desta API é organizado — vertical slices por domínio, o que fica em core, e por que a fatia é um pacote só com visibilidade package-private como fronteira. Use ao criar um domínio novo, ao decidir onde uma classe mora, ou ao precisar que uma fatia enxergue outra.
---

# Arquitetura

Domain-driven design com **vertical slices**. Cada domínio é um pacote direto sob `synapse.api`, e o pacote é a fronteira.

```
synapse/api/
├── ApiApplication.java
├── core/                    ← kernel técnico, consumido por todas as fatias
│   ├── config/
│   ├── logging/
│   └── metrics/
├── commissioning/           ← fatia
├── sales/                   ← fatia
└── approval/                ← fatia
```

Não existe segmento `domains/`. O caminho já diz que é domínio pelo fato de não ser `core`, e o segmento extra não carrega informação nem muda visibilidade — diferente de linguagens onde a pasta tem semântica.

## Um pacote por fatia, não por camada

Esta é a decisão que faz a fatia ser real em vez de decorativa.

```
commissioning/                        commissioning/
├── CommissioningController.java  ✅  ├── controller/   ❌
├── CommissioningService.java         ├── service/
├── Rule.java                         ├── repository/
└── RuleRepository.java               └── model/
```

Na forma da esquerda, tudo que não é porta de entrada da fatia pode ser **package-private** — sem modificador. `sales` fisicamente não compila se tentar tocar em `Rule`. O compilador enforça a fronteira.

Na forma da direita, `Rule` precisa ser `public` para o pacote `service` enxergar, e nesse instante fica visível para o projeto inteiro. A fatia vira convenção que ninguém verifica.

O Spring lida bem com isso: o component scan encontra `@Service`, `@Component` e `@RestController` package-private normalmente.

## Visibilidade como regra

Dentro de uma fatia, o padrão é **package-private**. `public` é decisão deliberada, e significa "outras fatias podem depender disto".

Em `core` é o inverso: tudo é `public`, porque ele existe para ser consumido.

O `@SpringBootApplication` mora em `synapse.api` e varre `synapse.api.**` para baixo, então fatia nova é encontrada sem configuração nenhuma.

## Quando uma fatia precisa de outra

Nesta ordem de preferência:

1. **Não precisar.** Duplicar um punhado de campos costuma custar menos que acoplar dois domínios.
2. **Evento** — `ApplicationEventPublisher`, e a outra fatia escuta. Mantém a dependência em uma direção só.
3. **Interface pública explícita** na fatia dona, com o mínimo de superfície.

Nunca alcançar o repositório ou as entidades da outra fatia direto.

## O que é core e o que não é

`core` é infraestrutura técnica: configuração, logging, métricas. Nada ali conhece regra de negócio.

Regra de negócio nunca mora em `core`, mesmo compartilhada por duas fatias — nesse caso ou ela pertence a uma delas, ou é uma fatia própria.

## Referências

- Configuração consumida pelas fatias: [`configuration`](../configuration/SKILL.md)
- Visibilidade e portão de build: [`code-quality`](../code-quality/SKILL.md)
