<script setup lang="ts">
import EntradaVoz from '@/components/EntradaVoz.vue'
defineProps<{ enviando: boolean }>()
const emit = defineEmits<{ enviar: [audio: Blob] }>()
</script>

<template>
  <EntradaVoz :enviando="enviando" @enviar="emit('enviar', $event)" />
</template>
