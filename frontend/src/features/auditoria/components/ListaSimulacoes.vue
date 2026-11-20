<script setup lang="ts">
import { formatarReais } from '@/composables/apresentacaoDetalhamento'
import {
  dataAuditoria,
  percentualAuditoria,
  situacaoDoResultado,
  vereditoAuditoria,
} from '../composables/apresentacaoAuditoria'
import type { SimulacaoLigada } from '../composables/simulacoesDossie'
import IdCopiavel from './IdCopiavel.vue'
defineProps<{ simulacoes: SimulacaoLigada[]; selecionada?: string }>()
defineEmits<{ selecionar: [id: string] }>()
</script>
<template>
  <section class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8">
    <p class="text-xs font-semibold tracking-wide text-[#a74700]">
      {{ simulacoes.length }} SIMULAÇÕES · ORDEM CRONOLÓGICA
    </p>
    <h2 class="mb-6 mt-3 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
      Histórico completo de simulações
    </h2>
    <p v-if="!simulacoes.length">Nenhuma simulação registrada.</p>
    <div v-else class="overflow-x-auto rounded-xl">
      <table class="w-full min-w-[56rem] text-left text-sm">
        <thead class="bg-[#fff0e9]">
          <tr>
            <th class="p-3 pl-5">Simulação / regra</th>
            <th class="p-3">Horário</th>
            <th class="p-3">Parâmetros de entrada</th>
            <th class="p-3">Saídas</th>
            <th class="p-3 pr-5">Situação</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in simulacoes"
            :key="item.simulacao.id"
            :data-simulacao="item.numero"
            :class="item.simulacao.id === selecionada ? 'bg-[#fff0e9]' : ''"
            class="border-t border-[#f1ded3] align-top"
          >
            <td class="p-3 pl-5">
              <p class="font-semibold">Simulação {{ item.numero }}</p>
              <IdCopiavel
                :id="item.simulacao.id"
                :rotulo="`da simulação ${item.numero}`"
                somente-botao
              />
              <p class="mt-1 text-xs">
                Versão {{ item.versao ? item.versao.versao : 'não identificada' }}
              </p>
              <p v-if="item.codigo" class="mt-1 text-xs">
                Código
                <IdCopiavel :id="item.codigo.id" :rotulo="`do código da simulação ${item.numero}`" somente-botao />
              </p>
            </td>
            <td class="whitespace-nowrap p-3">{{ dataAuditoria(item.simulacao.criado_em) }}</td>
            <td class="p-3 text-xs">
              <p>
                Competências:
                {{ item.parametros.competencias.join(', ') || 'Não informadas' }}
              </p>
              <p>
                Orçamento:
                {{ item.parametros.orcamento != null ? formatarReais(item.parametros.orcamento) : 'Não informado' }}
              </p>
              <p>
                Meta de venda:
                {{ item.parametros.meta_venda != null ? formatarReais(item.parametros.meta_venda) : 'Não informada' }}
              </p>
            </td>
            <td class="p-3 text-xs">
              <template v-if="item.resultado?.status === 'sucesso' && item.resultado.totais">
                <p>Baseline: {{ formatarReais(item.resultado.totais.baseline) }}</p>
                <p>Simulado: {{ formatarReais(item.resultado.totais.simulado) }}</p>
                <p>
                  Diferença: {{ formatarReais(item.resultado.totais.diferenca_abs) }} ({{
                    percentualAuditoria(item.resultado.totais.diferenca_pct)
                  }})
                </p>
              </template>
              <p v-else>Sem totais</p>
            </td>
            <td class="p-3 pr-5">
              <p class="font-semibold" :title="item.resultado?.status">
                {{ situacaoDoResultado(item.resultado?.status) }}
              </p>
              <p v-if="item.resultado?.status === 'sucesso'" class="text-xs" data-veredito>
                {{ vereditoAuditoria(item.resultado.veredito) }}
              </p>
              <button
                type="button"
                class="mt-2 cursor-pointer text-xs font-semibold text-[#a74700] underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
                :aria-pressed="item.simulacao.id === selecionada"
                @click="$emit('selecionar', item.simulacao.id)"
              >
                {{ item.simulacao.id === selecionada ? 'Selecionada' : 'Consultar registro →' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>