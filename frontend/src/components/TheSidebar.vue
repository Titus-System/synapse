<script setup lang="ts">
import simboloSynapse from '@/assets/imagens/synapse-simbolo.png'

interface RegraRecente {
  identificador: string
  rotulo: string
}

withDefaults(
  defineProps<{
    secaoAtiva?: 'salvas' | 'arquivadas'
    quantidadeArquivadas?: number
    quantidadeSalvas?: number
    regrasRecentes?: readonly RegraRecente[]
  }>(),
  {
    secaoAtiva: undefined,
    quantidadeArquivadas: 0,
    quantidadeSalvas: 0,
    regrasRecentes: () => [],
  },
)
</script>

<template>
  <aside class="flex min-h-full flex-col bg-[#3b2318] px-5 py-[clamp(.75rem,2.5vh,1.25rem)] text-[#f6eae3]">
    <div class="flex items-center gap-3">
      <img :src="simboloSynapse" alt="" class="size-9 object-contain" aria-hidden="true" />
      <span class="font-serif text-xl font-bold tracking-tight">Synapse</span>
    </div>

    <RouterLink
      to="/nova-regra"
      class="mt-[clamp(.75rem,2vh,1.5rem)] flex h-[clamp(2.25rem,5vh,2.75rem)] items-center justify-center gap-2 rounded-[10px] bg-[#f26b0f] text-sm font-medium text-white transition hover:bg-[#d95c08]"
    >
      <svg class="size-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
        <path d="M8 3.5v9M3.5 8h9" />
      </svg>
      Nova Regra
    </RouterLink>

    <section class="mt-4" aria-labelledby="titulo-recentes">
      <h2 id="titulo-recentes" class="text-sm font-normal text-[#c7afa3]">Recentes</h2>
      <ul class="mt-3 space-y-[clamp(.35rem,1.1vh,.625rem)]">
        <li v-for="regra in regrasRecentes" :key="regra.identificador">
          <RouterLink
            :to="`/jobs/${regra.identificador}`"
            class="flex h-[clamp(2rem,4.5vh,2.5rem)] items-center rounded-[10px] bg-[#4d3125] px-4 text-sm text-[#eaddd5] transition hover:bg-[#5a3b2c]"
          >
            {{ regra.rotulo }}
          </RouterLink>
        </li>
        <li v-if="regrasRecentes.length === 0" class="px-1 py-2 text-sm text-[#c7afa3]">
          Nenhuma regra criada ainda.
        </li>
      </ul>
    </section>

    <nav class="mt-auto border-t border-[#5a3e31] pt-3" aria-label="Organização de regras">
      <RouterLink to="/salvas" class="flex items-center gap-3 rounded-lg px-2 py-2.5 text-sm text-[#d6bdb0] transition hover:bg-[#4d3125]" :class="{ 'bg-[#4d3125] text-white': secaoAtiva === 'salvas' }">
        <svg class="size-[18px] shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2.25" />
          <path d="M2.75 8h14.5M7.5 8v8.25" />
        </svg>
        <span class="flex-1">Salvas</span>
        <span class="rounded-full bg-[#4d3125] px-2 py-0.5 text-xs text-[#d6bdb0]">{{ quantidadeSalvas }}</span>
      </RouterLink>
      <RouterLink to="/arquivadas" class="flex items-center gap-3 rounded-lg px-2 py-2.5 text-sm text-[#d6bdb0] transition hover:bg-[#4d3125]" :class="{ 'bg-[#4d3125] text-white': secaoAtiva === 'arquivadas' }">
        <svg class="size-[18px] shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2.25" />
          <path d="M2.75 8h14.5M7.5 8v8.25" />
        </svg>
        <span class="flex-1">Arquivadas</span>
        <span class="rounded-full bg-[#4d3125] px-2 py-0.5 text-xs text-[#d6bdb0]">{{ quantidadeArquivadas }}</span>
      </RouterLink>
    </nav>
  </aside>
</template>
