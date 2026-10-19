<script setup lang="ts">
import { watch } from 'vue'
import { useGravacao } from '@/composables/useGravacao'
const props = withDefaults(
  defineProps<{
    enviando: boolean
    bloqueada?: boolean
    compacto?: boolean
    jobId?: string
  }>(),
  { bloqueada: false, compacto: false },
)
const emit = defineEmits<{ enviar: [audio: Blob] }>()
const { gravando, solicitando, finalizando, audio, url, erro, iniciar, parar, descartar } =
  useGravacao(() => props.jobId)
watch(
  () => props.bloqueada || props.enviando,
  (bloqueada) => {
    if (bloqueada) descartar()
  },
)
watch(() => props.jobId, descartar)
function enviar() {
  if (
    !audio.value?.size ||
    props.enviando ||
    props.bloqueada ||
    gravando.value ||
    finalizando.value
  )
    return
  const gravacao = audio.value
  descartar()
  emit('enviar', gravacao)
}
</script>

<template>
  <div class="flex min-w-0 flex-col gap-3" :class="compacto ? 'w-full' : 'items-center'">
    <button
      type="button"
      :disabled="bloqueada || enviando || solicitando || finalizando"
      :aria-label="gravando ? 'Parar gravação' : 'Iniciar gravação'"
      class="self-start rounded-full bg-[#f97518] px-4 py-3 text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b65108] disabled:opacity-50"
      @click="gravando ? parar() : iniciar()"
    >
      {{
        enviando
          ? 'Enviando...'
          : solicitando
            ? 'Aguardando microfone...'
            : finalizando
              ? 'Preparando áudio...'
              : gravando
                ? 'Parar gravação'
                : audio
                  ? 'Gravar novamente'
                  : 'Gravar áudio'
      }}
    </button>
    <p role="status" class="text-sm">
      {{
        gravando
          ? 'Gravando. A gravação para automaticamente em 3 minutos.'
          : 'Grave até 3 minutos (máximo de 5 MB).'
      }}
    </p>
    <audio v-if="url" :src="url" controls class="w-full max-w-full" aria-label="Ouvir gravação" />
    <div class="flex flex-wrap gap-3">
      <button
        type="button"
        :disabled="!audio || gravando || finalizando || enviando || bloqueada"
        class="rounded-lg bg-[#a34b00] px-4 py-2 text-white focus-visible:outline-2 disabled:opacity-50"
        @click="enviar"
      >
        Enviar gravação
      </button>
      <button
        v-if="audio || gravando || solicitando"
        type="button"
        class="rounded-lg border px-4 py-2 focus-visible:outline-2"
        @click="descartar"
      >
        Descartar gravação
      </button>
    </div>
    <p v-if="erro" role="alert">{{ erro }}</p>
  </div>
</template>
