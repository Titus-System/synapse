<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  evidenciasDaVersao,
  finalizacaoDoDossie,
  ligarSimulacoes,
} from '../composables/simulacoesDossie'
import type { RegistroAuditoria, ResumoDossie } from '../types'
import ComparacaoSimulacoes from './ComparacaoSimulacoes.vue'
import DetalheSimulacao from './DetalheSimulacao.vue'
import FinalizacaoDossie from './FinalizacaoDossie.vue'
import ListaSimulacoes from './ListaSimulacoes.vue'
const props = defineProps<{
  registro: RegistroAuditoria
  resumo?: ResumoDossie
  carregandoResumo?: boolean
  erroResumo?: string
}>()
defineEmits<{ tentarNovamente: [] }>()
const simulacoes = computed(() =>
  ligarSimulacoes(props.registro, props.resumo?.comparacoes ?? []),
)
const escolhida = ref<string | undefined>(undefined)
watch(
  simulacoes,
  (lista) => {
    if (!lista.some((s) => s.simulacao.id === escolhida.value))
      escolhida.value = lista[lista.length - 1]?.simulacao.id
  },
  { immediate: true },
)
const atual = computed(() => simulacoes.value.find((s) => s.simulacao.id === escolhida.value))
const anterior = computed(() =>
  simulacoes.value.find(
    (s) =>
      atual.value?.comparacao &&
      s.resultado?.id === atual.value.comparacao.resultado_anterior_id,
  ),
)
const finalizacao = computed(() => finalizacaoDoDossie(props.registro))
const evidencias = computed(() =>
  evidenciasDaVersao(props.registro, simulacoes.value, props.resumo?.versao_vigente),
)
const contadores = computed(() => [
  { chave: 'registradas', texto: 'Simulações registradas', valor: props.resumo?.simulacoes.registradas },
  { chave: 'sucesso', texto: 'Concluídas com resultado', valor: props.resumo?.simulacoes.sucesso },
  { chave: 'falha', texto: 'Com falha', valor: props.resumo?.simulacoes.falha },
  {
    chave: 'vigente',
    texto: 'Versão vigente',
    valor: props.resumo?.versao_vigente != null ? `v${props.resumo.versao_vigente}` : undefined,
  },
])
</script>
<template>
  <div class="space-y-7">
    <p v-if="carregandoResumo" role="status">Carregando resumo…</p>
    <div v-else-if="erroResumo" role="alert" class="rounded-xl border border-[#dec0b1] bg-white p-5">
      <p>{{ erroResumo }}</p>
      <button
        type="button"
        class="mt-3 cursor-pointer rounded-lg bg-[#f87519] px-4 py-2 text-sm font-medium text-white"
        @click="$emit('tentarNovamente')"
      >
        Tentar novamente
      </button>
    </div>
    <div v-else class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" data-contadores>
      <div
        v-for="c in contadores"
        :key="c.chave"
        :data-contador="c.chave"
        class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm"
      >
        <p class="font-serif text-3xl font-bold">{{ c.valor ?? '—' }}</p>
        <p class="mt-1 text-sm text-[#806b5d]">{{ c.texto }}</p>
      </div>
    </div>
    <ListaSimulacoes
      :simulacoes="simulacoes"
      :responsavel="registro.job.usuario.login"
      :selecionada="escolhida"
      @selecionar="escolhida = $event"
    />
    <DetalheSimulacao v-if="atual" :item="atual" :responsavel="registro.job.usuario.login" />
    <ComparacaoSimulacoes v-if="atual" :item="atual" :anterior="anterior" />
    <div class="grid items-start gap-7 lg:grid-cols-2">
      <div class="space-y-4">
        <FinalizacaoDossie
          :finalizacao="finalizacao"
          :versao-vigente="resumo?.versao_vigente"
          :evidencias="evidencias"
          :regra="registro.job.nome || 'Regra sem nome'"
          :responsavel="registro.job.usuario.login"
        />
        <p
          role="note"
          class="flex gap-3 rounded-xl border border-[#dec0b1] bg-[#fff0e9] p-4 text-sm"
          data-aviso-auditor
        >
          <svg
            class="mt-0.5 size-4 shrink-0 text-[#a74700]"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM12 11v5M12 8h.01" />
          </svg>
          O auditor consulta a finalização feita no fluxo operacional; não pode finalizar,
          alterar nem reexecutar esta regra.
        </p>
      </div>
      <slot name="trilha" />
    </div>
  </div>
</template>