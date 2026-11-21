<script setup lang="ts">
import { computed } from 'vue'
import { formatarReais } from '@/composables/apresentacaoDetalhamento'
import {
  codigosAuditoria,
  dataAuditoria,
  destaqueDoVeredito,
  percentualAuditoria,
  sinalAuditoria,
  situacaoDoResultado,
  vereditoAuditoria,
} from '../composables/apresentacaoAuditoria'
import type { SimulacaoLigada } from '../composables/simulacoesDossie'
import FontesResultado from './FontesResultado.vue'
import IdCopiavel from './IdCopiavel.vue'
const props = defineProps<{ item: SimulacaoLigada; responsavel: string }>()
const nucleo = computed(() => props.item.versao?.representacao.nucleo)
const totais = computed(() =>
  props.item.resultado?.status === 'sucesso' ? props.item.resultado.totais : null,
)
const destaque = computed(() => destaqueDoVeredito(props.item.resultado?.veredito))
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
        <dd class="font-semibold" data-versao-utilizada>
          {{ item.versao ? `v${item.versao.versao}` : 'Versão não identificada' }} ·
          <template v-if="item.codigo">
            código
            <IdCopiavel
              :id="item.codigo.id"
              :rotulo="`do código da simulação ${item.numero}`"
              somente-botao
            />
          </template>
          <template v-else>código não identificado</template>
        </dd>
      </div>
      <div>
        <dt class="text-[#806b5d]">Responsável</dt>
        <dd class="break-all font-semibold" data-responsavel>{{ responsavel }}</dd>
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
    <div class="mt-6 grid items-start gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
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
            <dd class="font-semibold">{{ item.parametros.competencias.join(', ') || 'Não informadas' }}</dd>
          </div>
          <div>
            <dt class="text-[#806b5d]">Orçamento</dt>
            <dd class="font-semibold">
              {{ item.parametros.orcamento != null ? formatarReais(item.parametros.orcamento) : 'Não informado' }}
            </dd>
          </div>
          <div>
            <dt class="text-[#806b5d]">Meta de venda</dt>
            <dd class="font-semibold">
              {{ item.parametros.meta_venda != null ? formatarReais(item.parametros.meta_venda) : 'Não informada' }}
            </dd>
          </div>
        </dl>
      </div>
      <div class="space-y-4">
        <div v-if="totais" class="grid gap-4 sm:grid-cols-2" data-totais>
          <div :class="destaque" class="rounded-xl p-5" data-destaque="simulado">
            <p class="text-sm text-[#644b3e]">Simulado</p>
            <p class="mt-2 break-words font-serif text-2xl font-bold">{{ formatarReais(totais.simulado) }}</p>
            <p class="mt-2 text-xs text-[#644b3e]">Baseline: {{ formatarReais(totais.baseline) }}</p>
          </div>
          <div :class="destaque" class="rounded-xl p-5" data-destaque="diferenca">
            <p class="text-sm text-[#644b3e]">Diferença</p>
            <p class="mt-2 break-words font-serif text-2xl font-bold">
              {{ sinalAuditoria(formatarReais(totais.diferenca_abs), totais.diferenca_abs) }}
            </p>
            <p class="mt-2 text-xs text-[#644b3e]">
              {{ sinalAuditoria(percentualAuditoria(totais.diferenca_pct), totais.diferenca_pct) }} ·
              {{ vereditoAuditoria(item.resultado?.veredito) }}
            </p>
          </div>
        </div>
        <p v-else class="rounded-xl bg-[#fff0e9] p-5 text-sm" data-totais>
          Esta simulação não tem totais: {{ situacaoDoResultado(item.resultado?.status) }}.
        </p>
        <div v-if="item.explicacao" class="rounded-xl border border-[#dec0b1] p-5" data-explicacao>
          <h3 class="mb-2 font-serif text-lg font-bold">Explicação do resultado</h3>
          <p class="whitespace-pre-line text-sm">{{ item.explicacao.texto }}</p>
          <p
            v-if="!item.explicacao.aderencia_conferida"
            role="note"
            class="mt-3 text-xs font-semibold text-[#b42318]"
            data-sem-aderencia
          >
            Algum número citado neste texto não corresponde ao apurado.
          </p>
        </div>
        <div v-if="quebras.length" class="rounded-xl border border-[#dec0b1] p-5" data-quebras>
          <h3 class="mb-3 font-serif text-lg font-bold">Quebra da diferença</h3>
          <div class="grid items-start gap-3 sm:grid-cols-2">
            <details
              v-for="q in quebras"
              :key="q.chave"
              :data-quebra="q.chave"
              class="rounded-lg border border-[#dec0b1] p-3"
            >
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
        <p
          v-if="item.resultado"
          class="inline-block rounded-full bg-[#fff0e9] px-3 py-1 text-xs font-semibold text-[#644b3e]"
          data-selo-registro
        >
          Resultado registrado · sem execução pelo auditor
        </p>
      </div>
    </div>
    <FontesResultado v-if="item.resultado" :fontes="item.resultado.fontes" />
  </section>
</template>
