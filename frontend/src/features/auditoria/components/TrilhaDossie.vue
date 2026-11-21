<script setup lang="ts">
import IdCopiavel from './IdCopiavel.vue'
import {
  diaAuditoria,
  horaAuditoria,
  quemFezOEvento,
  situacaoDoEvento,
  tipoDoEvento,
} from '../composables/apresentacaoAuditoria'
import type { EventoAuditoria, TipoEventoAuditoria } from '../types'
defineProps<{ eventos?: EventoAuditoria[]; carregando: boolean; erro: string }>()
defineEmits<{ tentarNovamente: [] }>()
const ALVO = 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10ZM12 11v2'
const ICONES: Record<TipoEventoAuditoria, string> = {
  entrada: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 8h8M8 12h5',
  rodada_correcao: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5',
  versao_regra: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM3 12h6M15 12h6',
  codigo_gerado:
    'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M10 12l-2 2 2 2M14 12l2 2-2 2',
  resultado_simulacao: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM8.5 12l2.5 2.5 4.5-5',
  sugestao_meta_criada: ALVO,
  sugestao_meta_aceita: ALVO,
  acao_usuario: 'M5 21V4M5 4h11l-2 4 2 4H5',
  job_erro: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 8v5M12 16h.01',
}
function titulo(evento: EventoAuditoria) {
  const situacao = situacaoDoEvento(evento)
  return situacao === '—' ? tipoDoEvento(evento.tipo) : `${tipoDoEvento(evento.tipo)} · ${situacao}`
}
</script>
<template>
  <section class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8">
    <p class="text-xs font-semibold tracking-wide text-[#a74700]">
      ORDEM CRONOLÓGICA · HORÁRIO DE BRASÍLIA
    </p>
    <h2 class="mb-6 mt-3 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
      Trilha cronológica
    </h2>
    <p v-if="carregando" role="status">Carregando trilha…</p>
    <div v-else-if="erro" role="alert">
      <p>{{ erro }}</p>
      <button
        class="mt-5 cursor-pointer rounded-lg bg-[#f87519] px-5 py-3 text-sm font-medium text-white transition hover:bg-[#dd620c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
        @click="$emit('tentarNovamente')"
      >
        Tentar novamente
      </button>
    </div>
    <template v-else-if="eventos">
      <p v-if="!eventos.length">Nenhum evento registrado para esta regra.</p>
      <ol v-else aria-label="Trilha cronológica" class="space-y-5">
        <li
          v-for="evento in eventos"
          :key="`${evento.tipo}:${evento.origem_id}:${evento.instante}`"
          class="grid grid-cols-[1.25rem_6rem_minmax(0,1fr)] items-start gap-x-3"
        >
          <svg
            class="mt-0.5 size-5 text-[#a74700]"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path :d="ICONES[evento.tipo]" />
          </svg>
          <span class="font-mono text-xs leading-5 text-[#a74700]"
            >{{ diaAuditoria(evento.instante) }}<br />{{ horaAuditoria(evento.instante) }}</span
          >
          <div class="min-w-0">
            <p class="font-semibold text-[#2e1a10]">{{ titulo(evento) }}</p>
            <p class="mt-1 text-xs text-[#806b5d]">
              {{ quemFezOEvento(evento) }} ·
              <IdCopiavel
                :id="evento.origem_id"
                :rotulo="`do registro de ${tipoDoEvento(evento.tipo).toLowerCase()}`"
                somente-botao
              />
            </p>
          </div>
        </li>
      </ol>
    </template>
  </section>
</template>
