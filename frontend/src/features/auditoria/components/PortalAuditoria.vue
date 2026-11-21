<script setup lang="ts">
import simboloSynapse from '@/assets/imagens/synapse-simbolo.png'
withDefaults(defineProps<{ login?: string; regra?: string; secao?: 'operacoes' | 'dossies' }>(), {
  secao: 'dossies',
})
defineEmits<{ sair: [] }>()
</script>
<template>
  <div
    class="tela-de-negocio min-h-[100dvh] bg-[#fff8f5] font-sans text-[#644b3e] lg:grid lg:h-[100dvh] lg:grid-cols-[16rem_minmax(0,1fr)] lg:overflow-hidden xl:grid-cols-[20rem_minmax(0,1fr)]"
  >
    <aside
      class="flex min-h-0 flex-col gap-6 bg-[#3b2318] p-5 text-[#f6eae3] lg:h-full lg:overflow-y-auto"
      aria-label="Portal de auditoria"
    >
      <div class="flex items-center gap-3">
        <img :src="simboloSynapse" alt="" class="size-9 object-contain" aria-hidden="true" />
        <div>
          <span class="font-serif text-xl font-bold tracking-tight">Synapse</span>
          <p class="mt-1 text-[.625rem] tracking-widest text-[#c7afa3]">PORTAL DE AUDITORIA</p>
        </div>
      </div>
      <div class="hidden rounded-[.625rem] bg-[#4d3125] p-4 lg:block">
        <strong class="flex items-center gap-3 text-sm"
          ><svg
            class="size-5 text-[#d6bdb0]"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            aria-hidden="true"
          >
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
            <circle cx="12" cy="12" r="3" /></svg
          >Auditor</strong
        >
        <p class="mt-2 text-sm text-[#c7afa3]">Somente leitura</p>
      </div>
      <nav aria-label="Auditoria">
        <p class="mb-3 hidden text-xs tracking-wide text-[#c7afa3] lg:block">CONSULTA GLOBAL</p>
        <RouterLink
          to="/auditoria"
          :aria-current="secao === 'operacoes' ? 'page' : undefined"
          :class="secao === 'operacoes' ? 'bg-[#4d3125] text-white' : ''"
          class="mb-2 flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition hover:bg-[#5a3b2c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f26b0f]"
          ><svg
            class="size-5 shrink-0 text-[#f26b0f]"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            aria-hidden="true"
          >
            <path d="M4 6h16M4 12h16M4 18h10" /></svg
          >Todas as operações</RouterLink
        >
        <RouterLink
          to="/auditoria/dossies"
          :aria-current="secao === 'dossies' ? 'page' : undefined"
          :class="secao === 'dossies' ? 'bg-[#4d3125] text-white' : ''"
          class="flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-medium transition hover:bg-[#5a3b2c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f26b0f]"
          ><svg
            class="size-5 shrink-0 text-[#f26b0f]"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            aria-hidden="true"
          >
            <path d="M8 3h7l5 5v11a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
            <path d="M14 3v6h6M3 7v13a3 3 0 0 0 3 3" /></svg
          >Dossiês de regras</RouterLink
        >
      </nav>
      <div v-if="regra" class="hidden border-y border-[#5a3e31] py-5 lg:block">
        <p class="mb-3 text-xs text-[#c7afa3]">EM CONSULTA</p>
        <strong class="break-words text-sm">{{ regra }}</strong>
      </div>
      <p class="hidden text-sm leading-relaxed text-[#c7afa3] lg:block">
        Acesso separado do operacional. Consulte os registros de todos os usuários, sem alterar
        regras.
      </p>
      <div
        class="flex items-center justify-between gap-3 border-t border-[#5a3e31] pt-4 lg:mt-auto lg:block"
      >
        <div class="min-w-0">
          <p class="break-all text-sm font-semibold">{{ login }}</p>
          <p class="mt-1 hidden text-xs text-[#c7afa3] lg:block">Auditoria interna</p>
        </div>
        <button
          type="button"
          class="shrink-0 cursor-pointer rounded-lg px-2 py-2 text-sm text-[#d6bdb0] transition hover:bg-[#4d3125] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#f26b0f] lg:mt-3"
          @click="$emit('sair')"
        >
          Sair do portal →
        </button>
      </div>
    </aside>
    <div class="min-w-0 lg:min-h-0 lg:overflow-y-auto">
      <header
        class="flex min-h-20 flex-wrap items-center justify-between gap-4 border-b border-[#dec0b1] px-6 py-4 text-[#644b3e] lg:px-8"
      >
        <span class="min-w-0 break-words text-sm sm:text-base"
          >Portal de Auditoria / {{ secao === 'operacoes' ? 'Todas as operações' : 'Dossiês'
          }}<span v-if="regra"> / {{ regra }}</span></span
        ><span class="flex shrink-0 items-center gap-3 text-sm font-semibold"
          ><svg
            class="size-5 text-[#a74700]"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            aria-hidden="true"
          >
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
            <circle cx="12" cy="12" r="3" /></svg
          ><span class="rounded-full bg-[#fff0e9] px-4 py-2">Auditor · Somente leitura</span></span
        >
      </header>
      <main class="mx-auto max-w-[90rem] px-4 pb-14 pt-10 sm:px-8 lg:px-12 lg:pt-12 xl:px-16">
        <slot />
        <footer
          class="mt-12 flex flex-wrap justify-between gap-3 border-t border-[#dec0b1] pt-6 text-xs text-[#806b5d]"
        >
          <span>Synapse · Portal de Auditoria</span><span>Horários de Brasília · UTC−3</span>
        </footer>
      </main>
    </div>
  </div>
</template>
