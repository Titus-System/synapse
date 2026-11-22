<script setup lang="ts">
import { computed } from 'vue'
import type { CartaoHistorico } from '../composables/useHistoricoPaginado'
import { rotuloDaRegra } from '../composables/filtrosDoHistorico'
const props = defineProps<{ cartao: CartaoHistorico; arquivada: boolean }>()
defineEmits<{ detalhes: []; reprocessar: [] }>()
const nome = computed(() => rotuloDaRegra(props.cartao.resumo.id, props.cartao.resumo.nome))
const data = computed(() =>
  new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(props.cartao.resumo.criado_em)),
)
</script>

<template>
  <article
    class="grid gap-4 border-b border-[#fcf0eb] px-6 py-7 last:border-0 sm:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(10rem,.55fr)_auto] lg:items-center lg:gap-6 lg:py-9"
  >
    <div class="flex min-w-0 items-center gap-5">
      <span
        class="grid size-12 shrink-0 place-items-center rounded-xl bg-[#f5ede6] text-[#a74700]"
        aria-hidden="true"
      >
        <svg
          class="size-6"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linejoin="round"
        >
          <path d="M4 4h8l9 9-8 8-9-9z" />
          <circle cx="8" cy="8" r="1" />
          <path d="m11 13 2 2 4-4" />
        </svg>
      </span>
      <div class="min-w-0">
        <h2
          class="text-base font-medium break-words text-[#2e1a10] xl:text-lg"
          :title="cartao.contexto || undefined"
        >
          {{ nome }}
        </h2>
        <p v-if="cartao.falhou" role="alert" class="mt-2 text-sm text-[#9c3e19]">
          Não foi possível carregar os detalhes desta regra.
        </p>
      </div>
    </div>
    <time
      :datetime="cartao.resumo.criado_em"
      class="pl-17 text-sm text-[#644b3e] lg:pl-0 xl:text-base"
      >{{ data }}</time
    >
    <div class="flex flex-wrap items-center gap-4 pl-17 lg:justify-end lg:pl-0">
      <button
        type="button"
        class="flex cursor-pointer items-center gap-2 rounded-md py-2 text-sm text-[#644b3e] hover:text-[#ad4800] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#f87519]"
        :aria-label="`Detalhes de ${nome}`"
        @click="$emit('detalhes')"
      >
        Detalhes <span aria-hidden="true">›</span>
      </button>
      <button
        v-if="arquivada"
        type="button"
        class="cursor-pointer rounded-lg border border-[#e6c2af] px-3 py-2 text-sm font-medium text-[#a74700] hover:bg-[#fff1ea]"
        :aria-label="`Reprocessar ${nome}`"
        @click="$emit('reprocessar')"
      >
        Reprocessar
      </button>
    </div>
  </article>
</template>
