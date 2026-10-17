<script setup lang="ts">
import { useGravacao } from '../composables/useGravacao'
defineProps<{ enviando: boolean }>()
const emit = defineEmits<{ enviar: [audio: Blob] }>()
const { gravando, solicitando, audio, url, erro, iniciar, parar } = useGravacao()
</script>

<template>
  <div class="flex flex-col items-center gap-4">
    <button
      type="button"
      :disabled="enviando || solicitando"
      :aria-label="gravando ? 'Parar gravação' : 'Iniciar gravação'"
      class="rounded-full bg-[#f97518] px-8 py-5 text-white disabled:opacity-50"
      @click="gravando ? parar() : iniciar()"
    >
      {{
        solicitando
          ? 'Aguardando microfone...'
          : gravando
            ? 'Parar gravação'
            : audio
              ? 'Gravar novamente'
              : 'Iniciar gravação'
      }}
    </button>
    <p role="status">
      {{
        gravando
          ? 'Gravando. A gravação para automaticamente em 3 minutos.'
          : 'Grave até 3 minutos (máximo de 5 MB).'
      }}
    </p>
    <audio v-if="url" :src="url" controls aria-label="Ouvir gravação" />
    <button
      v-if="audio && !gravando"
      type="button"
      :disabled="enviando"
      class="rounded-lg bg-[#a34b00] px-7 py-3 text-white"
      @click="emit('enviar', audio)"
    >
      {{ enviando ? 'Enviando...' : 'Enviar gravação' }}
    </button>
    <p v-if="erro" role="alert">{{ erro }}</p>
  </div>
</template>
