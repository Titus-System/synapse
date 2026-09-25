# stores

Genuinely global state: shared across views or cached from the server. Nothing else lives here.

## Do

```ts
// features/<feature>/stores/example.ts — Pinia's "setup store" shape
export const useExampleStore = defineStore('example', () => {
  const items = ref<ExampleItem[]>([])
  async function fetchAll() { ... }
  return { items, fetchAll }
})
```

The id passed to `defineStore` is global in the app — prefix it with the feature name so two workstreams don't collide (`'example'`, `'simulation'`, never `'items'` or `'list'`).

## Don't

```ts
// ❌ local form/UI state doesn't become a store
export const useLoginFormStore = defineStore('loginForm', () => {
  const email = ref('')
  const showPassword = ref(false)
  return { email, showPassword }
})
```

That stays in a `ref` inside the view itself. A store per screen is an anti-pattern — if the state isn't shared across views or cached from the server, it isn't a store candidate.

## Acompanhar o progresso de um job

Para acompanhar o progresso de um job, é preciso chamar `usarStoreJobAtual()` para acessar o singleton da store localmente.

O chamador (a view) define o ciclo de vida do acompanhamento. Ele pode começar em um `watch` imediato do identificador da rota e deve terminar em `onBeforeUnmount`. Encerrar antes da desmontagem impede que a limpeza da tela anterior cancele o acompanhamento iniciado pela próxima tela na mesma store.

Com a store instanciada, o chamador pode iniciar o acompanhamento chamando `store.iniciarAcompanhamento(jobId)` e parar chamando `store.pararAcompanhamento()`, conforme o exemplo:

```ts
const route = useRoute()
const store = usarStoreJobAtual() // same singleton instance everywhere this is called

watch(() => route.params.id, (id) => {
  void store.iniciarAcompanhamento(String(id))
}, { immediate: true })
onBeforeUnmount(() => store.pararAcompanhamento()) // leaving without this keeps the SSE stream open

```

`iniciarAcompanhamento` abre o SSE e consulta a fotografia inicial por HTTP. Eventos de estado, resultado, conclusão de etapa e reconexão disparam nova consulta. A store ignora respostas de consultas anteriores e eventos de acompanhamentos encerrados.

`aplicarJob` recebe respostas de ações; `aplicarConfirmacao` recebe a resposta com `regra` e invalida consultas anteriores. As views selecionam a maior `versao` de `regras` com `regraMaisRecente` e usam `simulacaoVisivel` para não exibir resultados anteriores durante uma nova execução.

Não chamar `store.pararAcompanhamento()` deixa a conexão SSE aberta.


## Contributing

A feature's store is born in `features/<feature>/stores/`. This root directory (`src/stores/`) is only for what **two or more features** legitimately share (e.g. the authenticated user's session) — promoted by the same rule of two that applies to components and types.
