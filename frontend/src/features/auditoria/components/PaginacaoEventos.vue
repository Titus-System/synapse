<script setup lang="ts">
import { computed } from 'vue'
import { paginasVisiveis } from '../composables/paginacaoEventos'
const props = defineProps<{ pagina: number; tamanho: number; total: number; quantidade: number }>()
defineEmits<{ ir: [pagina: number] }>()
const primeiro = computed(() => (props.quantidade ? props.pagina * props.tamanho + 1 : 0))
const ultimo = computed(() => props.pagina * props.tamanho + props.quantidade)
const numeros = computed(() => paginasVisiveis(props.pagina, props.total, props.tamanho))
const temProxima = computed(() => (props.pagina + 1) * props.tamanho < props.total)
</script>
<template>
  <nav
    aria-label="Paginação dos eventos"
    class="flex flex-wrap items-center justify-between gap-4 border-t border-[#f1ded3] px-6 py-5 text-sm"
  >
    <span class="text-[#806b5d]"
      >{{ primeiro }}–{{ ultimo }} de {{ total }} eventos · {{ tamanho }} por página</span
    >
    <div class="flex items-center gap-1">
      <button
        type="button"
        :disabled="pagina === 0"
        class="min-h-10 cursor-pointer rounded-lg px-3 text-[#806b5d] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700] disabled:cursor-default disabled:opacity-40"
        @click="$emit('ir', pagina - 1)"
      >
        ← Anterior
      </button>
      <button
        v-for="numero in numeros"
        :key="numero"
        type="button"
        :aria-label="`Página ${numero + 1}`"
        :aria-current="numero === pagina ? 'page' : undefined"
        :class="
          numero === pagina
            ? 'bg-[#a74700] font-semibold text-white'
            : 'text-[#644b3e] hover:bg-[#fff0e9]'
        "
        class="size-10 cursor-pointer rounded-lg transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
        @click="numero !== pagina && $emit('ir', numero)"
      >
        {{ numero + 1 }}
      </button>
      <button
        type="button"
        :disabled="!temProxima"
        class="min-h-10 cursor-pointer rounded-lg px-3 font-medium text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700] disabled:cursor-default disabled:opacity-40"
        @click="$emit('ir', pagina + 1)"
      >
        Próxima →
      </button>
    </div>
  </nav>
</template>
