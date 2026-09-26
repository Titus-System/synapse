<script setup lang="ts">
withDefaults(
  defineProps<{
    id: string
    rotulo: string
    valor: string
    erro?: string
    ajuda?: string
    placeholder?: string
    tipo?: 'text' | 'number'
    prefixo?: string
    sufixo?: string
    compacto?: boolean
  }>(),
  { erro: '', ajuda: '', placeholder: '', tipo: 'text', prefixo: '', sufixo: '' },
)

const emitir = defineEmits<{
  'update:valor': [valor: string]
  sair: []
}>()
</script>

<template>
  <div>
    <label :for="id" :class="compacto ? 'sr-only' : 'block text-sm font-medium text-[#3a241a]'">{{ rotulo }}</label>
    <p v-if="ajuda" :id="`${id}-ajuda`" :class="compacto ? 'sr-only' : 'mt-1 text-sm text-[#6b564a]'">{{ ajuda }}</p>
    <div :class="compacto ? 'relative' : 'relative mt-2'">
      <span v-if="prefixo" class="pointer-events-none absolute inset-y-0 left-0 grid w-9 place-items-center text-sm text-[#8a7366]">
        {{ prefixo }}
      </span>
      <input
        :id="id"
        :value="valor"
        :type="tipo"
        :inputmode="tipo === 'number' ? 'decimal' : undefined"
        :placeholder="placeholder"
        :aria-describedby="[ajuda ? `${id}-ajuda` : '', erro ? `${id}-erro` : ''].filter(Boolean).join(' ') || undefined"
        :aria-invalid="Boolean(erro)"
        class="h-[2.125rem] w-full rounded-[.4375rem] border bg-[#faf4ef] px-3 text-sm text-[#2e1a10] outline-none transition placeholder:text-[#b09a8d] focus:border-[#c2560b] focus:ring-2 focus:ring-[#f4dcc9]"
        :class="[
          erro ? 'border-[#c0392b]' : 'border-[#e3d3c9]',
          prefixo ? 'pl-9' : '',
          sufixo ? 'pr-9' : '',
          compacto ? '' : 'h-11 bg-white',
        ]"
        @input="emitir('update:valor', ($event.target as HTMLInputElement).value)"
        @blur="emitir('sair')"
      />
      <span v-if="sufixo" class="pointer-events-none absolute inset-y-0 right-0 grid w-9 place-items-center text-sm text-[#8a7366]">
        {{ sufixo }}
      </span>
    </div>
    <p v-if="erro" :id="`${id}-erro`" class="mt-1.5 text-sm text-[#c0392b]" role="alert">{{ erro }}</p>
  </div>
</template>
