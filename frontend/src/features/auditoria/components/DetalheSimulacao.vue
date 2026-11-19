<script setup lang="ts">
import { computed } from 'vue'
import { formatarReais } from '@/composables/apresentacaoDetalhamento'
import {
  codigosAuditoria,
  dataAuditoria,
  percentualAuditoria,
  situacaoDoResultado,
  vereditoAuditoria,
} from '../composables/apresentacaoAuditoria'
import type { SimulacaoLigada } from '../composables/simulacoesDossie'
import IdCopiavel from './IdCopiavel.vue'
const props = defineProps<{ item: SimulacaoLigada }>()
const nucleo = computed(() => props.item.versao?.representacao.nucleo)
const competencias = computed(
  () => (props.item.versao?.parametros?.competencias as string[] | undefined) ?? [],
)
const totais = computed(() =>
  props.item.resultado?.status === 'sucesso' ? props.item.resultado.totais : null,
)
const quebras = computed(() => {
  const d = props.item.resultado?.status === 'sucesso' ? props.item.resultado.decomposicao : null
  if (!d) return []
  return [
    { chave: 'loja', titulo: 'Por loja', itens: Object.entries(d.loja) },
    { chave: 'marca', titulo: 'Por marca', itens: Object.entries(d.marca) },
    { chave: 'cargo', titulo: 'Por cargo', itens: Object.entries(d.cargo) },
    { chave: 'competencia', titulo: 'Por competência', itens: Object.entries(d.competencia) },
  ]
})
</script>
<template>
  <section
    class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8"
    aria-label="Simulação selecionada"
  >
    <p class="text-xs font-semibold tracking-wide text-[#a74700]">
      SIMULAÇÃO {{ item.numero }} · {{ situacaoDoResultado(item.resultado?.status).toUpperCase() }}
    </p>
    <h2 class="mb-6 mt-3 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
      Simulação selecionada · {{ item.numero }}
    </h2>
    <dl class="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
      <div>
        <dt class="text-[#806b5d]">Versão utilizada</dt>
        <dd class="font-semibold">{{ item.versao ? `v${item.versao.versao}` : 'Não identificada' }}</dd>
      </div>
      <div>
        <dt class="text-[#806b5d]">Código</dt>
        <dd class="font-semibold"><IdCopiavel v-if="item.codigo" :id="item.codigo.id" /><span v-else>Não identificado</span></dd>
      </div>
      <div>
        <dt class="text-[#806b5d]">Data e hora</dt>
        <dd class="font-semibold">{{ dataAuditoria(item.simulacao.criado_em) }}</dd>
      </div>
      <div>
        <dt class="text-[#806b5d]">Situação</dt>
        <dd class="font-semibold">{{ situacaoDoResultado(item.resultado?.status) }}</dd>
      </div>
    </dl>
    <div class="mt-6 grid gap-4 lg:grid-cols-2">
      <div class="rounded-xl bg-[#fff0e9] p-5">
        <h3 class="mb-3 font-serif text-lg font-bold">Parâmetros de entrada</h3>
        <dl class="space-y-2 text-sm">
          <div data-escopo>
            <dt class="text-[#806b5d]">Loja / marca / cargo (códigos)</dt>
            <dd class="font-semibold">
              {{ codigosAuditoria(nucleo?.loja) }} / {{ codigosAuditoria(nucleo?.marca) }} /
              {{ codigosAuditoria(nucleo?.cargo) }}
            </dd>
          </div>
          <div>
            <dt class="text-[#806b5d]">Competências</dt>
            <dd class="font-semibold">{{ competencias.join(', ') || 'Não informadas' }}</dd>
          </div>
          <div>
            <dt class="text-[#806b5d]">Orçamento</dt>
            <dd class="font-semibold">
              {{ totais?.orcamento != null ? formatarReais(totais.orcamento) : 'Não informado' }}
            </dd>
          </div>
          <div>
            <dt class="text-[#806b5d]">Meta de venda</dt>
            <dd class="font-semibold">
              {{ item.resultado?.meta_venda != null ? formatarReais(item.resultado.meta_venda) : 'Não informada' }}
            </dd>
          </div>
        </dl>
      </div>
      <div class="rounded-xl bg-[#fff0e9] p-5" data-totais>
        <h3 class="mb-3 font-serif text-lg font-bold">Totais</h3>
        <dl v-if="totais" class="space-y-2 text-sm">
          <div class="flex justify-between gap-3"><dt>Baseline</dt><dd class="font-semibold">{{ formatarReais(totais.baseline) }}</dd></div>
          <div class="flex justify-between gap-3"><dt>Simulado</dt><dd class="font-semibold">{{ formatarReais(totais.simulado) }}</dd></div>
          <div class="flex justify-between gap-3">
            <dt>Diferença</dt>
            <dd class="font-semibold">{{ formatarReais(totais.diferenca_abs) }} ({{ percentualAuditoria(totais.diferenca_pct) }})</dd>
          </div>
          <div class="flex justify-between gap-3"><dt>Veredito</dt><dd class="font-semibold">{{ vereditoAuditoria(item.resultado?.veredito) }}</dd></div>
        </dl>
        <p v-else class="text-sm">Esta simulação não tem totais: {{ situacaoDoResultado(item.resultado?.status) }}.</p>
      </div>
    </div>
    <div v-if="quebras.length" class="mt-6" data-quebras>
      <h3 class="mb-3 font-serif text-lg font-bold">Quebra da diferença</h3>
      <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <details v-for="q in quebras" :key="q.chave" :data-quebra="q.chave" class="rounded-lg border border-[#dec0b1] p-3">
          <summary class="cursor-pointer font-semibold">{{ q.titulo }}</summary>
          <p v-if="!q.itens.length" class="mt-2 text-sm">Sem valores.</p>
          <dl v-else class="mt-2 max-h-56 space-y-1 overflow-auto text-sm">
            <div v-for="[codigo, valor] in q.itens" :key="codigo" class="flex justify-between gap-2">
              <dt>{{ q.chave === 'competencia' ? codigo : `Código ${codigo}` }}</dt>
              <dd class="font-semibold">{{ formatarReais(valor) }}</dd>
            </div>
          </dl>
        </details>
      </div>
    </div>
  </section>
</template>