<script setup lang="ts">
import { computed } from 'vue'
import type { RegraVersionada, Simulacao, StatusJob } from '@/types/api'

const props = defineProps<{
  regra: RegraVersionada | null
  simulacao: Simulacao | null
  status: StatusJob | null
  podeAceitar: boolean
  podeCancelar: boolean
}>()
defineEmits<{ aceitar: []; cancelar: [] }>()

const processando = computed(() => props.status === 'gerando_regra' || props.status === 'simulando')
const interrompida = computed(() => props.status === 'erro')
const sucesso = computed(() => props.simulacao?.status === 'sucesso')
const viavel = computed(() => sucesso.value && props.simulacao?.veredito === 'viavel')
const percentual = computed(() => {
  const valor = props.regra?.representacao.nucleo.percentual
  return valor == null ? '' : new Intl.NumberFormat('pt-BR', {
    style: 'percent', maximumFractionDigits: 4,
  }).format(valor)
})
const total = computed(() => {
  const valor = sucesso.value ? props.simulacao?.resultado?.totais?.simulado : null
  return valor == null ? '' : `R$ ${valor.toLocaleString('pt-BR', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  })}`
})
const vigencia = computed(() => {
  const valor = props.regra?.representacao.nucleo.vigencia
  if (!valor) return ''
  const formatar = (mes: string) => mes.split('-').reverse().join('/')
  return valor.inicio === valor.fim ? formatar(valor.inicio)
    : `${formatar(valor.inicio)} até ${formatar(valor.fim)}`
})
</script>

<template>
  <section aria-labelledby="titulo-sugestao" class="mx-auto mb-8 w-full max-w-6xl px-4 sm:px-6 lg:px-10">
    <h2 id="titulo-sugestao" class="mb-2 text-3xl font-semibold text-[#2B160D]">Sugestão</h2>
    <div v-if="!regra" role="status" class="rounded-lg border border-[#DFC0B2] bg-[#F4ECE6]/50 p-5 text-[#584237]">
      <p class="mb-3 font-bold text-[#2B160D]">Nenhuma sugestão disponível no momento.</p>
      <p class="mb-3">
        O método atual só sugere alternativas para regras com percentual simples, sem condições adicionais,
        quando o orçamento fica acima do custo de referência (baseline) e abaixo do total simulado.
        Fora dessas condições, o método atual não consegue propor uma alternativa automaticamente.
      </p>
      <p>Isso não significa que seja impossível encontrar uma regra que caiba no orçamento. Você pode revisar a regra e fazer uma nova simulação.</p>
      <RouterLink to="/nova-regra" class="mt-4 inline-block underline">Revisar em uma nova regra</RouterLink>
    </div>
    <p v-else-if="processando" role="status" class="text-[#584237]">
      <template v-if="status === 'gerando_regra'">Estamos preparando a regra alternativa para a simulação.</template>
      <template v-else>Estamos simulando uma alternativa com percentual menor. Aguarde o resultado para decidir.</template>
    </p>
    <div v-else-if="interrompida || (simulacao?.status && !sucesso)" role="status" class="text-[#B45309]">
      <p>Não foi possível concluir a simulação da alternativa. O resultado da regra original permanece acima.</p>
      <RouterLink to="/nova-regra" class="mt-4 inline-block underline">Revisar em uma nova regra</RouterLink>
    </div>
    <template v-else-if="sucesso && regra">
      <p class="mb-6 text-[#584237]">Simulamos uma alternativa que reduz o percentual e mantém os demais campos da regra.</p>
      <div class="flex flex-col gap-6 lg:flex-row">
        <div class="min-w-0 flex-1">
          <h3 class="mb-4 font-bold">Regra sugerida</h3>
          <dl class="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div><dt class="text-[#584237]">Vigência</dt><dd>{{ vigencia }}</dd></div>
            <div><dt class="text-[#584237]">Loja</dt><dd>{{ regra.representacao.nucleo.loja?.join(', ') }}</dd></div>
            <div><dt class="text-[#584237]">Marca</dt><dd>{{ regra.representacao.nucleo.marca?.join(', ') }}</dd></div>
            <div><dt class="text-[#584237]">Cargo</dt><dd>{{ regra.representacao.nucleo.cargo?.join(', ') }}</dd></div>
            <div><dt class="text-[#584237]">Percentual sugerido</dt><dd data-testid="percentual-sugestao" class="font-bold">{{ percentual }}</dd></div>
          </dl>
        </div>
        <div class="min-w-0 flex-1 rounded-lg border-2 border-[#DFC0B2] p-5">
          <h3 class="mb-4 font-bold">Simulação da sugestão</h3>
          <label for="total-sugestao" class="mb-1 block text-[#584237]">Total de comissionamento</label>
          <input id="total-sugestao" :value="total" readonly class="mb-4 w-full rounded-lg border-2 border-[#8B7265] bg-[#FFE9E1] px-3.5 py-3 text-[#2B160D]">
          <p v-if="viavel" class="mb-4 font-bold text-[#14532D]">A sugestão cabe no seu orçamento.</p>
          <p v-else-if="simulacao?.veredito === 'inviavel'" class="mb-4 text-[#950606]">A alternativa ainda excede o orçamento. Revise a regra para tentar outra simulação.</p>
          <p v-else class="mb-4 text-[#B45309]">Não foi possível determinar se a alternativa cabe no orçamento.</p>
          <p v-if="podeAceitar" class="mb-3">Deseja escolher essa nova regra?</p>
          <div class="flex flex-col gap-3 sm:flex-row">
            <button v-if="podeAceitar" type="button" class="rounded-lg bg-[#14532D] px-5 py-3 text-white" @click="$emit('aceitar')">Aceitar sugestão e finalizar</button>
            <RouterLink v-else to="/nova-regra" class="rounded-lg border border-[#DFC0B2] px-5 py-3 text-center text-[#8f470e]">Revisar em uma nova regra</RouterLink>
            <button v-if="podeCancelar" type="button" class="rounded-lg border border-[#950606] px-5 py-3 text-[#950606]" @click="$emit('cancelar')">Recusar e cancelar</button>
          </div>
        </div>
      </div>
    </template>
    <p v-else role="status" class="text-[#584237]">Aguardando o resultado da simulação da alternativa.</p>
  </section>
</template>
