<script setup lang="ts">
import { computed, ref } from 'vue'
import FiltrosAvancadosRepositorio from './FiltrosAvancadosRepositorio.vue'
import {
  OPCOES_DE_ORDENACAO,
  OPCOES_DE_PERIODO,
  quantidadeDeFiltrosAvancados,
  type FiltrosDoHistorico,
} from '../composables/filtrosDoHistorico'

defineProps<{ total?: number; competencias: string[]; buscando: boolean }>()
const filtros = defineModel<FiltrosDoHistorico>('filtros', { required: true })
const avancadosAbertos = ref(false)
const avancadosAtivos = computed(() => quantidadeDeFiltrosAvancados(filtros.value))

function atualizar<C extends keyof FiltrosDoHistorico>(campo: C, valor: FiltrosDoHistorico[C]) {
  filtros.value = { ...filtros.value, [campo]: valor }
}
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
        aria-label="Ordenação"
        class="min-w-0 cursor-pointer bg-transparent text-[#2e1a10]"
        :value="filtros.ordenacao"
        @change="
          atualizar(
            'ordenacao',
            ($event.target as HTMLSelectElement).value as FiltrosDoHistorico['ordenacao'],
          )
        "
      >
        <option v-for="opcao in OPCOES_DE_ORDENACAO" :key="opcao.valor" :value="opcao.valor">
          {{ opcao.rotulo }}
        </option>
      </select>
    </label>
    <label
      class="flex min-h-12 items-center gap-2 rounded-2xl bg-white px-4 py-3 text-sm shadow-sm"
    >
      Período:
      <select
        aria-label="Período"
        class="cursor-pointer bg-transparent text-[#2e1a10]"
        :value="filtros.periodo"
        @change="
          atualizar(
            'periodo',
            ($event.target as HTMLSelectElement).value as FiltrosDoHistorico['periodo'],
          )
        "
      >
        <option v-for="opcao in OPCOES_DE_PERIODO" :key="opcao.valor" :value="opcao.valor">
          {{ opcao.rotulo }}
        </option>
      </select>
    </label>
  </div>
  <div class="mb-4 flex flex-col gap-4 sm:flex-row" aria-label="Busca e filtros">
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
        placeholder="Pesquisar por nome da regra, lógica SE/ENTÃO, variáveis ou operador…"
        class="h-16 w-full rounded-2xl bg-white pr-5 pl-14 text-sm shadow-sm placeholder:text-[#ac998e] focus-visible:outline-2 focus-visible:outline-[#f87519]"
        :value="filtros.busca"
        @input="atualizar('busca', ($event.target as HTMLInputElement).value)"
      />
    </label>
    <button
      type="button"
      class="flex h-16 cursor-pointer items-center justify-center gap-3 rounded-2xl px-6 font-medium shadow-sm"
      :class="avancadosAbertos ? 'bg-[#fff0e9]' : 'bg-white hover:bg-[#fff8f5]'"
      aria-controls="filtros-avancados"
      :aria-expanded="avancadosAbertos"
      @click="avancadosAbertos = !avancadosAbertos"
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
      <span
        v-if="avancadosAtivos"
        class="grid size-6 place-items-center rounded-full bg-[#f87519] text-xs font-semibold text-white"
        :aria-label="`${avancadosAtivos} ativos`"
        >{{ avancadosAtivos }}</span
      >
    </button>
  </div>
  <p v-if="buscando" role="status" class="mb-4 px-2 text-sm text-[#806b5d]">
    Buscando também na lógica das regras…
  </p>
  <FiltrosAvancadosRepositorio
    v-if="avancadosAbertos"
    id="filtros-avancados"
    v-model:filtros="filtros"
    :competencias="competencias"
  />
  <div v-else class="mb-3"></div>
</template>
