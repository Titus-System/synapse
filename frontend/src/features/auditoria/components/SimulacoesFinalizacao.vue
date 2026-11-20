<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
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
      :selecionada="escolhida"
      @selecionar="escolhida = $event"
    />
    <DetalheSimulacao v-if="atual" :item="atual" />
    <ComparacaoSimulacoes v-if="atual" :item="atual" :anterior="anterior" />
    <FinalizacaoDossie :finalizacao="finalizacao" :versao-vigente="resumo?.versao_vigente" />
  </div>
</template>