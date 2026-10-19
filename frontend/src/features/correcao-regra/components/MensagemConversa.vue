<script setup lang="ts">
import simbolo from '@/assets/imagens/synapse-simbolo.png'
withDefaults(defineProps<{ usuario?: boolean }>(), { usuario: false })
</script>

<template>
  <div class="flex items-end gap-3 sm:gap-4" :class="usuario ? 'justify-end' : 'justify-start'">
    <img v-if="!usuario" :src="simbolo" alt="Assistente" class="mb-1 size-7 shrink-0 sm:size-9" />
    <div
      class="max-w-[85%] break-words px-4 py-4 text-base leading-relaxed shadow-sm sm:px-5 sm:text-lg"
      :class="
        usuario
          ? 'rounded-t-2xl rounded-bl-2xl bg-[#e7dfda] text-[#79736e]'
          : 'rounded-t-2xl rounded-br-2xl border border-[#ffdbcd] bg-[#fff1ec] text-[#584237]'
      "
    >
      <slot />
    </div>
    <span
      v-if="usuario"
      class="mb-1 grid size-9 shrink-0 place-items-center rounded-full bg-[#ffdbcd] text-[#72584b]"
      aria-label="Você"
    >
      <svg
        viewBox="0 0 24 24"
        class="size-5"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        aria-hidden="true"
      >
        <circle cx="12" cy="8" r="3" />
        <path d="M5 20v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2z" />
      </svg>
    </span>
  </div>
</template>
