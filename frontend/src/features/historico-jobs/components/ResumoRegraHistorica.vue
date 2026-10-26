<script setup lang="ts">
import { computed } from 'vue'
import type { RegraVersionada, Simulacao } from '@/types/api'
import { transformarRegra } from '@/composables/transformarRegra'
import { formatarReais } from '@/composables/apresentacaoDetalhamento'
import { origemDaVersao } from '../composables/historicoDoJob'

const props = defineProps<{
  regra: RegraVersionada
  simulacao?: Simulacao
  titulo: string
}>()
const logica = computed(() => transformarRegra(props.regra.representacao))
const data = computed(() =>
  new Date(props.regra.criada_em).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }),
)
const resultado = computed(() =>
  props.simulacao?.status === 'sucesso' ? props.simulacao.resultado : null,
)
</script>

<template>
  <article
    id="resumo-regra-historica"
    tabindex="-1"
    aria-labelledby="titulo-regra-historica"
    class="min-w-0 rounded-xl border border-[#DFC0B2] bg-white px-5 pt-7 shadow-[0_8px_24px_-20px_rgba(60,30,15,0.3)] outline-none sm:px-8 sm:pt-8"
  >
    <header class="border-b border-[#FFDBCD] pb-4">
      <slot name="titulo">
        <h1 id="titulo-regra-historica" class="font-serif text-xl font-bold text-[#2B160D]">
          {{ titulo }}
        </h1>
      </slot>
      <p class="mt-1 text-xs text-[#9D4400]">{{ origemDaVersao(regra) }} · {{ data }}</p>
    </header>
    <div class="my-5 rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-4 text-[#584237]">
      <h2 class="mb-3 font-serif text-xs font-bold tracking-wide text-[#8B7265]">
        LÓGICA ESTRUTURADA (PRÉ-VISUALIZAÇÃO)
      </h2>
      <div class="space-y-3 font-mono text-xs leading-5">
        <div>
          <p>SE</p>
          <ul class="pl-6">
            <li
              v-for="(linha, indice) in logica.se"
              :key="indice"
              class="break-words whitespace-pre-wrap"
            >
              {{ linha }}
            </li>
            <li v-if="simulacao?.meta_venda != null">
              meta de vendas = {{ formatarReais(simulacao.meta_venda) }}
            </li>
          </ul>
        </div>
        <div>
          <p>ENTÃO</p>
          <ul class="pl-6">
            <li
              v-for="(linha, indice) in logica.entao"
              :key="indice"
              class="break-words whitespace-pre-wrap"
            >
              {{ linha }}
            </li>
            <template v-if="resultado?.totais">
              <li>comissão = {{ formatarReais(resultado.totais.simulado) }}</li>
              <li v-if="resultado.totais.orcamento != null">
                orçamento de comissão = {{ formatarReais(resultado.totais.orcamento) }}
              </li>
            </template>
            <li v-if="!logica.entao.length && !resultado?.totais" class="text-[#8B7265]">
              Sem resultado de simulação disponível.
            </li>
          </ul>
        </div>
      </div>
    </div>
    <p v-if="simulacao?.flag_baixa_rastreabilidade" class="mb-5 text-sm text-[#765B1A]">
      Resultado com baixa rastreabilidade.
    </p>
    <slot />
  </article>
</template>
