<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ aceitaEm: string }>()
const data = computed(() =>
  new Date(props.aceitaEm).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }),
)
</script>

<template>
  <div class="mt-4 rounded-lg border border-[#14532D]/20 bg-[#14532D]/5 px-4 py-3 text-sm text-[#14532D]">
    <p class="font-semibold">Meta de vendas sugerida aceita</p>
    <p class="mt-1 text-xs text-[#584237]">
      Aceita em <time :datetime="aceitaEm">{{ data }}</time>.
    </p>
  </div>
</template>
