<script setup lang="ts">
import { computed } from 'vue'
import type { EntradaAuditoria } from '../types'
const props = defineProps<{ entrada: EntradaAuditoria }>()
// Com a transcrição pendente, a falta do modelo não indica um registro anterior ao modelo.
const transcrita = computed(
  () => props.entrada.texto !== undefined || props.entrada.transcrito_em !== undefined,
)
</script>
<template>
  <p
    v-if="entrada.tipo === 'voz' && entrada.transcricao_modelo"
    data-modelo-transcricao
  >
    Transcrito por {{ entrada.transcricao_modelo.provedor }} · modelo
    {{ entrada.transcricao_modelo.modelo
    }}<template v-if="entrada.transcricao_modelo.versao">
      · versão {{ entrada.transcricao_modelo.versao }}</template
    >
  </p>
  <p v-else-if="entrada.tipo === 'voz' && transcrita" data-sem-modelo>
    Modelo da transcrição não registrado.
  </p>
</template>
