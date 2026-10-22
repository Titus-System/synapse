<script setup lang="ts">
import { computed } from 'vue'
import type { RepresentacaoRegra, ResultadoLinhas, ResultadoSimulacao } from '@/types/api'
import TotaisDetalhamento from './TotaisDetalhamento.vue'
import TabelaDetalhamento from './TabelaDetalhamento.vue'
import { organizarLinhas } from '@/composables/apresentacaoDetalhamento'
const props = defineProps<{
  aberto: boolean
  carregando: boolean
  erro: string | null
  linhas?: ResultadoLinhas
  regra?: RepresentacaoRegra
  decomposicao?: ResultadoSimulacao['decomposicao']
}>()
defineEmits<{ alternar: []; tentarNovamente: [] }>()
const linhasOrdenadas = computed(() => organizarLinhas(props.linhas ?? {}))
</script>

<template>
  <section class="mx-4 mb-8 min-w-0 text-[#584237] sm:mx-8" aria-label="Relatório da simulação">
    <button
      type="button"
      class="flex cursor-pointer items-center gap-2 text-sm text-[#9D4400] hover:underline focus-visible:outline-2 focus-visible:outline-offset-4"
      :aria-expanded="aberto"
      aria-controls="relatorio-simulacao"
      @click="$emit('alternar')"
    >
      {{ aberto ? 'Fechar relatório' : 'Abrir relatório' }}
      <span aria-hidden="true">{{ aberto ? '⌃' : '⌄' }}</span>
    </button>
    <div v-if="aberto" id="relatorio-simulacao" class="mt-4" :aria-busy="carregando">
      <p v-if="carregando" role="status" class="py-6">Carregando relatório...</p>
      <div
        v-else-if="erro"
        role="alert"
        class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-4"
      >
        <p>{{ erro }}</p>
        <button
          type="button"
          class="mt-3 cursor-pointer text-[#9D4400] underline"
          @click="$emit('tentarNovamente')"
        >
          Tentar novamente
        </button>
      </div>
      <p
        v-else-if="!linhas || !linhasOrdenadas.length"
        role="status"
        class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-4"
      >
        O detalhamento não está disponível para esta simulação.
      </p>
      <template v-else>
        <TotaisDetalhamento :decomposicao="decomposicao" matricula="" loja="" competencia="" />
        <TabelaDetalhamento :linhas="linhasOrdenadas" :regra="regra" />
      </template>
    </div>
  </section>
</template>
