<script setup lang="ts">
import type { AudioEntrada } from '../types'
defineProps<{ audio?: AudioEntrada; formato?: string }>()
const emit = defineEmits<{ ouvir: []; falhou: [] }>()
</script>
<template>
  <div class="text-sm" data-reprodutor-audio>
    <p v-if="!formato || audio?.estado === 'indisponivel'" class="text-[#806b5d]">
      Áudio indisponível para esta entrada.
    </p>
    <button
      v-else-if="!audio"
      type="button"
      class="cursor-pointer rounded-lg border border-[#a74700] bg-white px-4 py-2 font-semibold text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
      @click="emit('ouvir')"
    >
      ▶ Ouvir áudio
    </button>
    <p v-else-if="audio.estado === 'carregando'" role="status">Carregando áudio…</p>
    <audio
      v-else-if="audio.estado === 'pronto'"
      :src="audio.url"
      controls
      autoplay
      class="w-full max-w-md"
      aria-label="Áudio gravado da entrada"
      @error="emit('falhou')"
    />
    <div v-else role="alert" class="flex flex-wrap items-center gap-3">
      <span>Não foi possível carregar o áudio.</span>
      <button
        type="button"
        class="cursor-pointer rounded-lg border border-[#a74700] bg-white px-4 py-2 font-semibold text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
        @click="emit('ouvir')"
      >
        Tentar novamente
      </button>
    </div>
  </div>
</template>
