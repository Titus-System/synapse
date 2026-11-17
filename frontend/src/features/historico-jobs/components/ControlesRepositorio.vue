<script setup lang="ts">
defineProps<{ total?: number }>()
</script>

<template>
  <div class="mb-5 flex flex-wrap items-center gap-4 text-[#644b3e]">
    <p
      class="mr-auto flex min-h-12 items-center gap-3 rounded-2xl bg-white px-5 py-3 font-medium shadow-sm"
      aria-live="polite"
    >
      <span class="size-2.5 rounded-full bg-[#a74700]" aria-hidden="true"></span>
      <template v-if="total !== undefined"
        >Total: {{ total }} {{ total === 1 ? 'regra registrada' : 'regras registradas' }}</template
      >
      <template v-else>Total: —</template>
    </p>
    <label
      class="flex min-h-12 items-center gap-2 rounded-2xl bg-white px-4 py-3 text-sm shadow-sm"
    >
      Ordenar:
      <select
        disabled
        aria-label="Ordenação"
        title="Outras ordenações ainda não estão disponíveis."
        class="min-w-0 cursor-not-allowed bg-transparent text-[#2e1a10]"
      >
        <option>Mais recentes primeiro</option>
      </select>
    </label>
    <label
      class="flex min-h-12 items-center gap-2 rounded-2xl bg-white px-4 py-3 text-sm shadow-sm"
    >
      Período:
      <select
        disabled
        aria-label="Período"
        title="O filtro por período ainda não está disponível."
        class="cursor-not-allowed bg-transparent text-[#2e1a10]"
      >
        <option>Todos os períodos</option>
      </select>
    </label>
  </div>
  <div class="mb-7 flex flex-col gap-4 sm:flex-row" aria-label="Busca e filtros indisponíveis">
    <label class="relative min-w-0 flex-1">
      <span class="sr-only">Pesquisar regras</span>
      <svg
        class="absolute top-1/2 left-5 size-5 -translate-y-1/2 text-[#9c8272]"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        aria-hidden="true"
      >
        <circle cx="10" cy="10" r="6" />
        <path d="m15 15 6 6" />
      </svg>
      <input
        type="search"
        disabled
        placeholder="Pesquisar por nome da regra, lógica SE/ENTÃO, variáveis ou operador…"
        title="A pesquisa ainda não está disponível."
        class="h-16 w-full cursor-not-allowed rounded-2xl bg-white pr-5 pl-14 text-sm shadow-sm placeholder:text-[#ac998e]"
      />
    </label>
    <button
      type="button"
      disabled
      title="Os filtros avançados ainda não estão disponíveis."
      class="flex h-16 cursor-not-allowed items-center justify-center gap-3 rounded-2xl bg-white px-6 font-medium shadow-sm"
    >
      <svg
        class="size-5 text-[#a74700]"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        aria-hidden="true"
      >
        <path d="M3 6h18M3 12h18M3 18h18M8 3v6M16 9v6M8 15v6" />
      </svg>
      Filtros Avançados
    </button>
  </div>
</template>
