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
  () => props.bloqueada,
  (bloqueada) => {
    if (bloqueada) descartar()
  },
)
watch(() => props.jobId, descartar)
// A gravação só sai daqui quando a tela a bloqueia ou desmonta: um envio que falha
// precisa dela para a nova tentativa.
function enviar() {
  if (
    !audio.value?.size ||
    props.enviando ||
    props.bloqueada ||
    gravando.value ||
    finalizando.value
  )
    return
  emit('enviar', audio.value)
}
</script>

<template>
  <template v-if="compacto">
    <div
      v-if="solicitando || gravando || finalizando || audio || erro"
      class="absolute inset-x-0 bottom-full mb-3 flex flex-col gap-3 rounded-[1.25rem] border border-[#e6c5b8] bg-[#fff8f6] p-4 text-left shadow-sm"
    >
      <p role="status" class="text-sm text-[#584237]">
        {{
          solicitando
            ? 'Aguardando microfone...'
            : finalizando
              ? 'Preparando áudio...'
              : gravando
                ? 'Gravando. A gravação para automaticamente em 3 minutos.'
                : 'Grave até 3 minutos (máximo de 5 MB).'
        }}
      </p>
      <audio
        v-if="url && !gravando"
        :src="url"
        controls
        class="w-full max-w-full"
        aria-label="Ouvir gravação"
      />
      <div v-if="audio || gravando || solicitando" class="flex flex-wrap gap-3">
        <button
          v-if="audio && !gravando"
          type="button"
          :disabled="finalizando || enviando || bloqueada"
          class="rounded-lg bg-[#a34b00] px-4 py-2 text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b65108] disabled:cursor-not-allowed disabled:opacity-50"
          @click="enviar"
        >
          Enviar gravação
        </button>
        <button
          type="button"
          class="rounded-lg border border-[#e6c5b8] bg-white px-4 py-2 text-[#584237] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b65108]"
          @click="descartar"
        >
          Descartar gravação
        </button>
      </div>
      <p v-if="erro" role="alert" class="text-sm text-[#584237]">{{ erro }}</p>
    </div>
    <button
      type="button"
      :disabled="bloqueada || enviando || solicitando || finalizando"
      :aria-label="gravando ? 'Parar gravação' : 'Iniciar gravação'"
      class="grid size-12 shrink-0 place-items-center rounded-full border text-[#c2560b] transition hover:bg-[#ffebe3] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b65108] disabled:cursor-not-allowed disabled:opacity-40"
      :class="gravando ? 'border-[#f97518] bg-[#ffebe3]' : 'border-[#e6c5b8] bg-white'"
      @click="gravando ? parar() : iniciar()"
    >
      <svg
        v-if="gravando"
        class="size-5"
        viewBox="0 0 24 24"
        fill="currentColor"
        aria-hidden="true"
      >
        <rect x="6" y="6" width="12" height="12" rx="2" />
      </svg>
      <svg
        v-else
        class="size-6"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <rect x="9" y="2" width="6" height="13" rx="3" />
        <path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3" />
      </svg>
    </button>
  </template>
  <div v-else class="flex flex-col items-center">
    <button
      type="button"
      :disabled="bloqueada || enviando || solicitando || finalizando"
      :aria-label="gravando ? 'Parar gravação' : 'Iniciar gravação'"
      class="grid size-28 place-items-center rounded-full bg-[#f97518] text-white shadow-[0_16px_40px_-16px_rgba(249,117,24,0.45)] transition hover:bg-[#dc610d] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#b65108] disabled:cursor-not-allowed disabled:opacity-60 sm:size-36"
      @click="gravando ? parar() : iniciar()"
    >
      <svg
        v-if="gravando"
        class="size-10"
        viewBox="0 0 24 24"
        fill="currentColor"
        aria-hidden="true"
      >
        <rect x="6" y="6" width="12" height="12" rx="2" />
      </svg>
      <svg
        v-else
        class="size-12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <rect x="9" y="2" width="6" height="13" rx="3" />
        <path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3" />
      </svg>
    </button>
    <p role="status" class="mt-6 text-sm text-[#8c7b72] sm:text-base">
      {{
        enviando
          ? 'Enviando...'
          : solicitando
            ? 'Aguardando microfone...'
            : finalizando
              ? 'Preparando áudio...'
              : gravando
                ? 'Gravando. A gravação para automaticamente em 3 minutos.'
                : audio
                  ? 'Clique para gravar novamente'
                  : 'Clique para iniciar a gravação'
      }}
    </p>
    <p v-if="!gravando" class="mt-1 text-xs text-[#9d8274]">
      Grave até 3 minutos (máximo de 5 MB).
    </p>
    <template v-if="url && !gravando">
      <audio :src="url" controls class="mt-6 w-full max-w-md" aria-label="Ouvir gravação" />
      <div class="mt-4 flex flex-wrap justify-center gap-3">
        <button
          type="button"
          :disabled="enviando || bloqueada || finalizando"
          class="h-12 rounded-[1.25rem] bg-[#a34b00] px-7 font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b65108] disabled:cursor-not-allowed disabled:opacity-60"
          @click="enviar"
        >
          {{ enviando ? 'Enviando...' : 'Enviar gravação' }}
        </button>
        <button
          type="button"
          :disabled="enviando"
          class="h-12 rounded-[1.25rem] border border-[#e6c5b8] bg-white px-7 font-medium text-[#584237] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b65108] disabled:cursor-not-allowed disabled:opacity-60"
          @click="descartar"
        >
          Descartar gravação
        </button>
      </div>
    </template>
    <p v-if="erro" role="alert" class="mt-4 text-sm">{{ erro }}</p>
  </div>
</template>
