<script setup lang="ts">
import { computed, ref } from 'vue'
import type { StatusJob } from '@/types/api'
import { usarStoreSessao } from '@/stores/session'

type EtapaDoProcesso = 'voz-texto' | 'simulacao' | 'salvar'

const props = defineProps<{
  etapaDaRota: EtapaDoProcesso | null
  statusDoJob?: StatusJob | null
}>()

const sessao = usarStoreSessao()
const saindoDaConta = ref(false)

const rotulosDasEtapas: Record<EtapaDoProcesso, string> = {
  'voz-texto': 'Voz/Texto',
  simulacao: 'Simulação',
  salvar: 'Salvar',
}

const etapasPorStatus: Partial<Record<StatusJob, EtapaDoProcesso>> = {
  aguardando_transcricao: 'voz-texto',
  aguardando_confirmacao_parametros: 'simulacao',
  gerando_regra: 'simulacao',
  simulando: 'simulacao',
  simulacao_inviavel: 'simulacao',
  aguardando_decisao_usuario: 'simulacao',
  liberado: 'salvar',
}

const etapaAtual = computed<EtapaDoProcesso | null>(() => {
  if (props.statusDoJob === undefined) return props.etapaDaRota

  if (props.etapaDaRota === 'salvar') {
    return 'salvar'
  }

  return props.statusDoJob ? (etapasPorStatus[props.statusDoJob] ?? null) : null
})

const rotuloDaEtapaAtual = computed(() => (etapaAtual.value ? rotulosDasEtapas[etapaAtual.value] : ''))

function etapaEstaAtiva(etapa: EtapaDoProcesso): boolean {
  return etapaAtual.value === etapa
}

async function sairDaConta(): Promise<void> {
  saindoDaConta.value = true
  try {
    await sessao.sair()
  } finally {
    saindoDaConta.value = false
  }
}
</script>

<template>
  <header class="flex h-14 items-center gap-3 border-b border-[#ebd8cc] bg-[#fffaf7] px-4 sm:gap-6 sm:px-6 lg:h-16 lg:px-8">

    <ol v-if="etapaAtual" class="hidden min-w-0 flex-1 items-center justify-center gap-3 text-sm xl:flex" aria-label="Etapas do processo">
      <li
        class="flex shrink-0 items-center gap-2.5"
        :class="etapaEstaAtiva('voz-texto') ? 'font-medium text-[#c2560b]' : 'text-[#a79489]'"
        :aria-current="etapaEstaAtiva('voz-texto') ? 'step' : undefined"
      >
        <span
          class="grid size-[2.125rem] place-items-center rounded-full"
          :class="etapaEstaAtiva('voz-texto') ? 'border-[0.09375rem] border-[#c2560b]' : 'border-[0.0625rem] border-[#e5d3c8]'"
          aria-hidden="true"
        >
          <svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><rect x="7.25" y="2.75" width="5.5" height="9.5" rx="2.75" /><path d="M4.75 9.5a5.25 5.25 0 0 0 10.5 0M10 14.75v2.5" /></svg>
        </span>
        Voz/Texto
      </li>
      <li class="h-px min-w-6 flex-1 bg-[#e5d3c8]" aria-hidden="true"></li>
      <li
        class="flex shrink-0 items-center gap-2.5"
        :class="etapaEstaAtiva('simulacao') ? 'font-medium text-[#c2560b]' : 'text-[#a79489]'"
        :aria-current="etapaEstaAtiva('simulacao') ? 'step' : undefined"
      >
        <span
          class="grid size-[2.125rem] place-items-center rounded-full"
          :class="etapaEstaAtiva('simulacao') ? 'border-[0.09375rem] border-[#c2560b]' : 'border-[0.0625rem] border-[#e5d3c8]'"
          aria-hidden="true"
        >
          <svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><circle cx="10" cy="10" r="7.25" /><path d="M8.25 7.1 13 10l-4.75 2.9z" /></svg>
        </span>
        Simulação
      </li>
      <li class="h-px min-w-6 flex-1 bg-[#e5d3c8]" aria-hidden="true"></li>
      <li
        class="flex shrink-0 items-center gap-2.5"
        :class="etapaEstaAtiva('salvar') ? 'font-medium text-[#c2560b]' : 'text-[#a79489]'"
        :aria-current="etapaEstaAtiva('salvar') ? 'step' : undefined"
      >
        <span
          class="grid size-[2.125rem] place-items-center rounded-full"
          :class="etapaEstaAtiva('salvar') ? 'border-[0.09375rem] border-[#c2560b]' : 'border-[0.0625rem] border-[#e5d3c8]'"
          aria-hidden="true"
        >
          <svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M3.75 5.25a1.5 1.5 0 0 1 1.5-1.5h7.5l3 3v8a1.5 1.5 0 0 1-1.5 1.5h-9a1.5 1.5 0 0 1-1.5-1.5z" /><path d="M6.75 3.75v4h6.5M6.75 16.25v-4h6.5v4" /></svg>
        </span>
        Salvar
      </li>
    </ol>

    <p
      v-if="etapaAtual"
      class="min-w-0 flex-1 truncate text-center text-xs font-medium text-[#6b564a] sm:text-sm xl:hidden"
      :aria-label="`Etapa atual: ${rotuloDaEtapaAtual}`"
      aria-live="polite"
    >
      Etapa: {{ rotuloDaEtapaAtual }}
    </p>

    <details class="relative ml-auto shrink-0">
      <summary aria-label="Abrir menu de perfil" class="grid size-8 cursor-pointer list-none place-items-center rounded-full bg-[#6d4030] text-white transition hover:bg-[#512d20] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#c2560b] [&::-webkit-details-marker]:hidden">
        <svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="8" r="3.25" /><path d="M5.75 20c.55-3.27 2.94-5.25 6.25-5.25s5.7 1.98 6.25 5.25" /></svg>
      </summary>
      <div class="absolute top-[calc(100%+.5rem)] right-0 z-10 w-52 rounded-lg border border-[#ead4c7] bg-white p-3 shadow-[0_12px_30px_-12px_rgba(60,30,15,0.35)]">
        <p class="text-sm font-semibold text-[#2e1a10]">Perfil do usuário</p>
        <p class="mt-1 text-xs leading-5 text-[#80695c]">Encerre a sessão para trocar de conta.</p>
        <button type="button" :disabled="saindoDaConta" class="mt-3 flex w-full items-center justify-center gap-2 rounded-md border border-[#e4cfc3] px-3 py-2 text-sm font-medium text-[#6d4030] transition hover:bg-[#fff6f1] disabled:cursor-not-allowed disabled:opacity-70" @click="sairDaConta">
          {{ saindoDaConta ? 'Saindo…' : 'Sair da conta' }}
        </button>
      </div>
    </details>
  </header>
</template>
