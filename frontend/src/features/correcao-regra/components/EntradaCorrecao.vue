<script setup lang="ts">
defineProps<{ texto: string; habilitada: boolean; podeEnviar: boolean }>()
const emit = defineEmits<{ 'update:texto': [valor: string]; enviar: [] }>()
</script>

<template>
  <form
    class="relative flex items-center gap-3 rounded-[1.25rem] border border-[#e6c5b8] bg-[#fff8f6] p-2 shadow-sm"
    @submit.prevent="emit('enviar')"
  >
    <label for="texto-correcao" class="sr-only">Sua correção</label>
    <textarea
      id="texto-correcao"
      :value="texto"
      :disabled="!habilitada"
      rows="1"
      placeholder="Digite sua resposta aqui..."
      aria-describedby="limite-correcao"
      class="min-h-12 min-w-0 flex-1 resize-none rounded-xl bg-transparent px-2 py-3 text-base text-[#584237] outline-none placeholder:text-[#a38a7e] focus-visible:ring-2 focus-visible:ring-[#f97518] disabled:opacity-60"
      @input="emit('update:texto', ($event.target as HTMLTextAreaElement).value)"
    />
    <button
      type="submit"
      aria-label="Enviar correção"
      :disabled="!podeEnviar"
      class="grid size-12 shrink-0 place-items-center rounded-full bg-[#f97518] text-white shadow-md transition hover:bg-[#dc610d] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b65108] disabled:cursor-not-allowed disabled:opacity-40"
    >
      <svg class="size-6" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="m3 3 20 9-20 9v-7l13-2-13-2z" />
      </svg>
    </button>
  </form>
  <p
    id="limite-correcao"
    class="mt-2 text-right text-xs"
    :class="texto.length > 4000 ? 'text-red-700' : 'text-[#9d8274]'"
  >
    {{ texto.length }} / 4000 caracteres
  </p>
</template>
