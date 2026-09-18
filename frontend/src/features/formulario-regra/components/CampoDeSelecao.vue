<script setup lang="ts">
defineProps<{
  id: string
  rotulo: string
  valor: string
  opcoes: readonly { valor: string; rotulo: string }[]
  erro?: string
  compacto?: boolean
}>()

const emitir = defineEmits<{ 'update:valor': [valor: string] }>()
</script>

<template>
  <div>
    <label :for="id" :class="compacto ? 'sr-only' : 'block text-sm font-medium text-[#3a241a]'">{{ rotulo }}</label>
    <div :class="compacto ? 'relative' : 'relative mt-2'">
      <select
        :id="id"
        :value="valor"
        :aria-invalid="Boolean(erro)"
        :aria-describedby="erro ? `${id}-erro` : undefined"
        class="h-[clamp(1.75rem,4vh,2.125rem)] w-full appearance-none rounded-[7px] border bg-[#faf4ef] pr-8 pl-3 text-sm text-[#2e1a10] outline-none transition focus:border-[#c2560b] focus:ring-2 focus:ring-[#f4dcc9]"
        :class="[erro ? 'border-[#c0392b]' : 'border-[#e3d3c9]', compacto ? '' : 'mt-2 h-11 bg-white']"
        @change="emitir('update:valor', ($event.target as HTMLSelectElement).value)"
      >
        <option value="">Selecione uma opção</option>
        <option v-for="opcao in opcoes" :key="opcao.valor" :value="opcao.valor">
          {{ opcao.rotulo }}
        </option>
      </select>
      <svg
        class="pointer-events-none absolute top-1/2 right-3 size-3 -translate-y-1/2 text-[#8a7366]"
        viewBox="0 0 12 12"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M2 4.25h8L6 9z" />
      </svg>
    </div>
    <p v-if="erro" :id="`${id}-erro`" class="mt-1.5 text-sm text-[#c0392b]" role="alert">{{ erro }}</p>
  </div>
</template>
