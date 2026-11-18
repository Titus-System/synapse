<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{ titulo: string; texto: string }>()
const copia = ref<'ocioso' | 'copiado' | 'falhou'>('ocioso')
async function copiar() {
  try {
    await navigator.clipboard.writeText(props.texto)
    copia.value = 'copiado'
  } catch {
    copia.value = 'falhou'
  }
}
</script>
<template>
  <div class="mt-3">
    <div class="mb-2 flex items-center justify-between gap-3">
      <h4 class="text-sm font-semibold text-[#2e1a10]">{{ titulo }}</h4>
      <div class="flex items-center gap-2">
        <span v-if="copia === 'copiado'" role="status" class="text-xs">Copiado.</span>
        <span v-else-if="copia === 'falhou'" role="alert" class="text-xs">
          Não foi possível copiar.
        </span>
        <button
          type="button"
          class="cursor-pointer rounded-lg border border-[#a74700] px-3 py-1 text-xs font-semibold text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
          @click="copiar"
        >
          Copiar {{ titulo.toLowerCase() }}
        </button>
      </div>
    </div>
    <pre
      class="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-[#fff0e9] p-4 text-xs leading-6"
      tabindex="0"
      :aria-label="titulo"
      >{{ texto }}</pre>
  </div>
</template>