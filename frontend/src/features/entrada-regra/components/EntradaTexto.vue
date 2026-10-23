<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

defineProps<{ enviando: boolean }>()
const emit = defineEmits<{ enviar: [] }>()
const descricao = defineModel<string>({ required: true })
const areaDeTexto = ref<HTMLTextAreaElement | null>(null)

// A altura acompanha o texto até o teto de max-h, que é proporcional à altura da janela.
function ajustarAltura() {
  const campo = areaDeTexto.value
  if (!campo) return
  campo.style.height = 'auto'
  const altura = campo.scrollHeight + campo.offsetHeight - campo.clientHeight
  if (altura > 0) campo.style.height = `${altura}px`
}

watch(descricao, ajustarAltura, { flush: 'post' })
onMounted(() => {
  ajustarAltura()
  window.addEventListener('resize', ajustarAltura)
})
onBeforeUnmount(() => window.removeEventListener('resize', ajustarAltura))
</script>

<template>
  <div class="mx-auto w-full max-w-3xl">
    <div class="flex flex-col gap-3 sm:flex-row sm:items-start">
      <label for="descricao-regra" class="sr-only">Descrição da regra</label>
      <textarea
        id="descricao-regra"
        ref="areaDeTexto"
        v-model="descricao"
        rows="2"
        maxlength="8000"
        aria-describedby="limite-descricao"
        placeholder="Escreva a regra de negócio..."
        class="max-h-[max(10rem,calc(100dvh-27rem))] min-h-16 min-w-0 flex-1 resize-none rounded-[1.25rem] border border-[#e6c5b8] bg-white px-5 py-4 text-base outline-none placeholder:text-[#a38a7e] focus-visible:ring-2 focus-visible:ring-[#f97518]"
      />
      <button
        type="button"
        :disabled="enviando || !descricao.trim() || descricao.length > 8000"
        @click="emit('enviar')"
        class="h-16 disabled:cursor-not-allowed rounded-[1.25rem] bg-[#a34b00] px-7 font-medium text-white"
      >
        {{ enviando ? 'Enviando...' : 'Enviar' }}
      </button>
    </div>
    <p id="limite-descricao" class="mt-2 text-left text-xs text-[#9d8274]">
      {{ descricao.length }} / 8000 caracteres
    </p>
  </div>
</template>
