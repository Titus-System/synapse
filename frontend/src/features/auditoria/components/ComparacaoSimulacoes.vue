<script setup lang="ts">
import { computed } from 'vue'
import { formatarReais } from '@/composables/apresentacaoDetalhamento'
import {
  dataAuditoria,
  percentualAuditoria,
  sinalAuditoria,
} from '../composables/apresentacaoAuditoria'
import type { SimulacaoLigada } from '../composables/simulacoesDossie'
import type { ComparacaoIndicador } from '../types'
const props = defineProps<{ item: SimulacaoLigada; anterior?: SimulacaoLigada }>()
interface Linha {
  chave: string
  nome: string
  valores: ComparacaoIndicador
  fracao: boolean
}
const linhas = computed<Linha[]>(() => {
  const c = props.item.comparacao
  if (!c) return []
  const todas: [string, string, ComparacaoIndicador | undefined, boolean][] = [
    ['baseline', 'Baseline', c.baseline, false],
    ['simulado', 'Simulado', c.simulado, false],
    ['diferenca_abs', 'Diferença', c.diferenca_abs, false],
    ['diferenca_pct', 'Diferença percentual', c.diferenca_pct, true],
    ['orcamento', 'Orçamento', c.orcamento, false],
    ['meta_venda', 'Meta de venda', c.meta_venda, false],
  ]
  return todas.flatMap(([chave, nome, valores, fracao]) =>
    valores ? [{ chave, nome, valores, fracao }] : [],
  )
})
const formatar = (valor: number, fracao: boolean) =>
  fracao ? percentualAuditoria(valor) : formatarReais(valor)
</script>
<template>
  <section
    v-if="item.comparacao"
    class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8"
    aria-label="Comparação com a simulação anterior"
  >
    <p class="text-xs font-semibold tracking-wide text-[#a74700]">
      SIMULAÇÃO {{ anterior ? anterior.numero : '—' }} → SIMULAÇÃO {{ item.numero }}
    </p>
    <h2 class="mb-6 mt-3 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
      Comparação com a simulação anterior
    </h2>
    <div class="overflow-x-auto">
      <table class="w-full min-w-[32rem] text-left text-sm">
        <thead class="bg-[#fff0e9]">
          <tr>
            <th class="p-3">Indicador</th>
            <th class="p-3" data-coluna="anterior">
              <template v-if="anterior">
                Simulação {{ anterior.numero }}
                <span class="block text-xs font-normal">{{ dataAuditoria(anterior.simulacao.criado_em) }}</span>
              </template>
              <template v-else>Anterior</template>
            </th>
            <th class="p-3" data-coluna="atual">
              Simulação {{ item.numero }}
              <span class="block text-xs font-normal">{{ dataAuditoria(item.simulacao.criado_em) }}</span>
            </th>
            <th class="p-3">Variação</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="l in linhas" :key="l.chave" :data-indicador="l.chave" class="border-t border-[#f1ded3]">
            <td class="p-3 font-semibold">{{ l.nome }}</td>
            <td class="p-3">{{ formatar(l.valores.anterior, l.fracao) }}</td>
            <td class="p-3 font-semibold text-[#a74700]">{{ formatar(l.valores.atual, l.fracao) }}</td>
            <td class="p-3">
              {{ sinalAuditoria(formatar(l.valores.variacao, l.fracao), l.valores.variacao) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>