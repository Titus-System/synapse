<script setup lang="ts">
import { computed } from 'vue'
import type { RegraVersionada, Simulacao } from '@/types/api'
import { nomesDoEscopo } from '@/services/catalogoRh'
import { percentuaisDaRegra, vigenciaDoNucleo } from '@/composables/apresentacaoNucleo'
import { formatarReais } from '@/composables/apresentacaoDetalhamento'
import AceiteMetaHistorica from './AceiteMetaHistorica.vue'

const props = defineProps<{
  regra: RegraVersionada
  simulacao?: Simulacao
  execucoes: Simulacao[]
  vigenteId?: string
  titulo: string
  anterior?: boolean
}>()
defineEmits<{ selecionarExecucao: [id: string] }>()
const campos = computed(() => {
  const nucleo = props.regra.representacao.nucleo
  return [
    {
      rotulo: 'Vigência',
      valor: nucleo.vigencia ? vigenciaDoNucleo(nucleo) : 'Não registrada nesta versão',
    },
    { rotulo: 'Cargo', valor: nomesDoEscopo('cargo', nucleo.cargo) },
    { rotulo: 'Loja', valor: nomesDoEscopo('loja', nucleo.loja) },
    {
      rotulo: 'Meta de vendas',
      valor:
        props.simulacao?.meta_venda == null
          ? 'Não registrada neste resultado'
          : formatarReais(props.simulacao.meta_venda),
    },
    { rotulo: 'Marca', valor: nomesDoEscopo('marca', nucleo.marca) },
    { rotulo: 'Percentual', valor: percentuaisDaRegra(props.regra.representacao) },
  ]
})
const orcamento = computed(() => props.simulacao?.resultado?.totais?.orcamento)
const total = computed(() => props.simulacao?.resultado?.totais?.simulado)
const veredito = computed(() => {
  if (props.simulacao?.status !== 'sucesso') return 'Execução sem resultado de sucesso'
  return props.simulacao.veredito === 'viavel'
    ? 'Resultado viável'
    : props.simulacao.veredito === 'inviavel'
      ? 'Resultado inviável'
      : 'Resultado sem veredito'
})
const viavel = computed(() => props.simulacao?.veredito === 'viavel')
const inviavel = computed(() => props.simulacao?.veredito === 'inviavel')
</script>

<template>
  <section :aria-labelledby="`titulo-versao-${regra.id}${anterior ? '-anterior' : ''}`" class="min-w-0">
    <header class="mb-7">
      <h2 :id="`titulo-versao-${regra.id}${anterior ? '-anterior' : ''}`" class="font-serif text-2xl text-[#2B160D]">
        {{ titulo }}
      </h2>
    </header>
    <label v-if="execucoes.length > 1" class="mb-5 flex flex-col gap-2 text-sm text-[#584237]">
      Execução da versão {{ regra.versao }}
      <select
        :value="simulacao?.id"
        class="min-w-0 max-w-full rounded-lg border border-[#DFC0B2] bg-white p-3"
        @change="$emit('selecionarExecucao', ($event.target as HTMLSelectElement).value)"
      >
        <option v-for="execucao in execucoes" :key="execucao.id" :value="execucao.id">
          {{ new Date(execucao.criado_em).toLocaleString('pt-BR') }} · {{ execucao.id
          }}{{ execucao.id === vigenteId ? ' · Resultado vigente' : '' }}
        </option>
      </select>
    </label>
    <div class="grid min-w-0 gap-6 lg:grid-cols-2">
      <div class="min-w-0 py-3">
        <h3 class="mb-4 flex items-center gap-2 border-b border-[#FFDBCD] pb-2 font-serif text-sm font-bold">
          <font-awesome-icon :icon="['fas', 'diagram-project']" class="text-[#c2560b]" />
          Regra Estruturada
        </h3>
        <dl class="grid min-w-0 gap-x-6 gap-y-3 sm:grid-cols-2">
          <div v-for="campo in campos" :key="campo.rotulo" class="min-w-0">
            <dt class="mb-1 text-xs text-[#8B7265]">{{ campo.rotulo }}</dt>
            <dd
              class="min-h-11 break-words rounded-lg border border-[#efd9d0] bg-[#FFE9E1] px-3 py-2.5 text-sm leading-5 text-[#2B160D]"
            >
              {{ campo.valor }}
            </dd>
          </div>
        </dl>
      </div>
      <section
        class="min-w-0 rounded-lg border border-[#DFC0B2] bg-white/40 p-5"
        :aria-label="`${anterior ? 'Resultado anterior' : 'Resultado histórico'} da versão ${regra.versao}`"
      >
        <h3 class="mb-4 flex items-center gap-2 border-b border-[#FFDBCD] pb-2 font-serif text-sm font-bold">
          <font-awesome-icon :icon="['fas', 'flask']" class="text-[#c2560b]" />
          Dados da simulação
        </h3>
        <p v-if="!simulacao" role="status" class="text-sm text-[#8B7265]">
          Sem simulação disponível.
        </p>
        <template v-else>
          <dl class="space-y-4">
            <div>
              <dt class="mb-1 text-xs text-[#8B7265]">Orçamento de comissão</dt>
              <dd class="rounded-lg border border-[#DFC0B2] bg-[#FFF1EC] px-3 py-2.5 text-sm">
                {{
                  orcamento == null ? 'Não registrado neste resultado' : formatarReais(orcamento)
                }}
              </dd>
            </div>
            <div>
              <dt class="mb-1 text-xs text-[#8B7265]">Total de comissionamento</dt>
              <dd class="rounded-lg border border-[#8B7265] bg-[#FFF1EC] px-3 py-2.5 text-sm">
                {{ total == null ? 'Não disponível neste resultado' : formatarReais(total) }}
              </dd>
            </div>
          </dl>
          <AceiteMetaHistorica
            v-if="simulacao.meta_sugerida_aceita_em"
            :aceita-em="simulacao.meta_sugerida_aceita_em"
          />
          <div
            v-if="viavel || inviavel"
            class="mt-4 flex gap-3 rounded-lg border-l-8 bg-[#F4ECE6]/50 p-3"
            :class="viavel ? 'border-[#14532D]/20 border-l-[#14532D]' : 'border-[#950606]/20 border-l-[#950606]'"
            role="status"
          >
            <svg
              v-if="viavel"
              class="mt-0.5 size-6 shrink-0 text-[#14532D]"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="m8 12 2.5 2.5L16 9" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <svg
              v-else
              class="mt-0.5 size-6 shrink-0 text-[#950606]"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="m9 9 6 6m0-6-6 6" stroke-linecap="round" />
            </svg>
            <div>
              <p class="font-bold" :class="viavel ? 'text-[#14532D]' : 'text-[#950606]'">
                {{
                  viavel
                    ? 'Resultado: Regra de negócio aprovada!'
                    : 'Resultado: Regra de negócio reprovada!'
                }}
              </p>
              <p class="mt-1 text-sm text-[#584237]">
                {{
                  viavel
                    ? 'A regra de negócio cabe no seu orçamento.'
                    : 'A regra de negócio não cabe no seu orçamento.'
                }}
              </p>
            </div>
          </div>
          <p v-else class="mt-4 text-sm text-[#584237]">{{ veredito }}</p>
          <p v-if="simulacao.id === vigenteId" class="mt-2 text-xs text-[#80695c]">
            Resultado vigente
          </p>
        </template>
      </section>
    </div>
  </section>
</template>
