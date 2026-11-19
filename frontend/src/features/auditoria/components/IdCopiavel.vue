<script setup lang="ts">
import { ref } from 'vue'
import { idCurto } from '../composables/apresentacaoAuditoria'
const props = defineProps<{ id: string; rotulo?: string }>()
const copia = ref<'ocioso' | 'copiado' | 'falhou'>('ocioso')
async function copiar() {
  try {
    await navigator.clipboard.writeText(props.id)
    copia.value = 'copiado'
  } catch {
    copia.value = 'falhou'
  }
}
</script>
<template>
  <span class="inline-flex flex-wrap items-center gap-2">
    <span class="font-mono text-xs" :title="id">{{ rotulo ? `${rotulo} ` : '' }}{{ idCurto(id) }}</span>
    <button
      type="button"
      class="cursor-pointer text-xs text-[#a74700] underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
      :aria-label="`Copiar id ${rotulo ?? ''}`.trim()"
      @click="copiar"
    >
      Copiar id
    </button>
    <span v-if="copia === 'copiado'" role="status" class="text-xs">Copiado.</span>
    <span v-else-if="copia === 'falhou'" role="alert" class="text-xs">Não foi possível copiar.</span>
  </span>
</template>