<script setup lang="ts">
import { computed } from 'vue'
import type { RegraVersionada, Simulacao, StatusJob } from '@/types/api'

const props = defineProps<{
  regra: RegraVersionada | null
  simulacao: Simulacao | null
  status: StatusJob | null
  meta: string
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
const loja = computed(() => props.regra?.representacao.nucleo.loja?.join(', ') ?? '')
const marca = computed(() => props.regra?.representacao.nucleo.marca?.join(', ') ?? '')
const cargo = computed(() => props.regra?.representacao.nucleo.cargo?.join(', ') ?? '')
</script>

<template>
  <section aria-labelledby="titulo-sugestao" class="mx-auto mb-12 w-full max-w-6xl px-4 sm:px-6 lg:px-10">
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
      <span data-testid="carregando-sugestao" aria-hidden="true" class="ml-2 inline-block size-4 animate-spin rounded-full border-2 border-[#FFDBCD] border-t-[#f26b0f] align-[-0.2em]"></span>
    </p>
    <div v-else-if="interrompida || (simulacao?.status && !sucesso)" role="status" class="text-[#B45309]">
      <p>Não foi possível concluir a simulação da alternativa. O resultado da regra original permanece acima.</p>
      <RouterLink to="/nova-regra" class="mt-4 inline-block underline">Revisar em uma nova regra</RouterLink>
    </div>
    <template v-else-if="sucesso && regra">
      <p class="mb-11 text-[#584237]">A regra de negócio escolhida é inviável. Mas não se preocupe, criamos esta para você:</p>
      <div class="flex flex-col gap-6 lg:flex-row">
        <div class="min-w-0 w-full lg:w-1/2">
          <h3 class="flex items-center gap-2 font-bold text-[#2B160D]">
            <font-awesome-icon :icon="['fas', 'diagram-project']" class="text-[#c2560b]" />
            Regra Estruturada
          </h3>
          <hr class="mb-4 w-full border border-[#FFDBCD]">
          <form class="flex flex-col gap-4 sm:flex-row sm:gap-8">
            <div class="flex min-w-0 flex-1 flex-col gap-4">
              <div class="flex flex-col">
                <label for="vigencia-sugestao" class="mb-1 text-[#584237]">Vigência</label>
                <input id="vigencia-sugestao" type="text" :value="vigencia" readonly class="w-full min-w-0 rounded-lg border-2 border-[#8B7265]/10 bg-[#FFE9E1] px-3.5 py-3 text-[#2B160D]">
              </div>
              <div class="flex flex-col">
                <label for="loja-sugestao" class="mb-1 text-[#584237]">Loja</label>
                <input id="loja-sugestao" type="text" :value="loja" readonly class="w-full min-w-0 rounded-lg border-2 border-[#8B7265]/10 bg-[#FFE9E1] px-3.5 py-3 text-[#2B160D]">
              </div>
              <div class="flex flex-col">
                <label for="marca-sugestao" class="mb-1 text-[#584237]">Marca</label>
                <input id="marca-sugestao" type="text" :value="marca" readonly class="w-full min-w-0 rounded-lg border-2 border-[#8B7265]/10 bg-[#FFE9E1] px-3.5 py-3 text-[#2B160D]">
              </div>
            </div>
            <div class="flex min-w-0 flex-1 flex-col gap-4">
              <div class="flex flex-col">
                <label for="cargo-sugestao" class="mb-1 text-[#584237]">Cargo</label>
                <input id="cargo-sugestao" type="text" :value="cargo" readonly class="w-full min-w-0 rounded-lg border-2 border-[#8B7265]/10 bg-[#FFE9E1] px-3.5 py-3 text-[#2B160D]">
              </div>
              <div class="flex flex-col">
                <label for="meta-sugestao" class="mb-1 text-[#584237]">Meta</label>
                <input id="meta-sugestao" type="text" :value="meta" readonly class="w-full min-w-0 rounded-lg border-2 border-[#8B7265]/10 bg-[#FFE9E1] px-3.5 py-3 text-[#2B160D]">
              </div>
              <div class="flex flex-col">
                <label for="percentual-sugestao" class="mb-1 text-[#584237]">Percentual</label>
                <input id="percentual-sugestao" data-testid="percentual-sugestao" type="text" :value="percentual" readonly class="w-full min-w-0 rounded-lg border-2 border-[#8B7265]/10 bg-[#FFE9E1] px-3.5 py-3 text-[#2B160D]">
              </div>
            </div>
          </form>
        </div>
        <div class="min-w-0 w-full rounded-lg border-2 border-[#DFC0B2] p-5 lg:w-1/2">
          <h3 class="flex items-center gap-2 font-bold text-[#2B160D]">
            <font-awesome-icon :icon="['fas', 'flask']" class="text-[#c2560b]" />
            Dados da simulação
          </h3>
          <hr class="mb-4 border border-[#FFDBCD]">
          <div class="mb-8 flex flex-col">
            <label for="total-sugestao" class="mb-1 text-[#584237]">Total de comissionamento</label>
            <input id="total-sugestao" :value="total" readonly placeholder="R$ X,00" class="w-full rounded-lg border-2 border-[#8B7265] bg-[#FFE9E1] px-3.5 py-3 text-[#2B160D]">
          </div>
          <p v-if="viavel" class="mb-4 font-bold text-[#14532D]">A sugestão cabe no seu orçamento.</p>
          <p v-else-if="simulacao?.veredito === 'inviavel'" class="mb-4 text-[#950606]">A alternativa ainda excede o orçamento. Revise a regra para tentar outra simulação.</p>
          <p v-else class="mb-4 text-[#B45309]">Não foi possível determinar se a alternativa cabe no orçamento.</p>
          <p v-if="podeAceitar" class="mb-3 text-xl font-semibold text-[#2B160D]">Deseja escolher essa nova regra?</p>
          <div class="flex flex-col gap-3 sm:flex-row">
            <button
              v-if="podeAceitar"
              type="button"
              class="flex flex-1 cursor-pointer flex-col rounded-lg border border-t-[#14532D]/20 border-r-[#14532D]/20 border-b-[#14532D]/20 border-l-8 border-l-[#14532D] bg-[#F4ECE6]/50 px-5 py-2 text-center"
              @click="$emit('aceitar')"
            >
              <span class="font-bold text-[#14532D]">SIM!</span>
              <span class="text-[#584237]">Seguir para a próxima etapa.</span>
            </button>
            <RouterLink v-else to="/nova-regra" class="rounded-lg border border-[#DFC0B2] px-5 py-3 text-center text-[#8f470e]">Revisar em uma nova regra</RouterLink>
            <button
              v-if="podeCancelar"
              type="button"
              class="flex flex-1 cursor-pointer flex-col rounded-lg border border-t-[#950606]/20 border-r-[#950606]/20 border-b-[#950606]/20 border-l-8 border-l-[#950606] bg-[#F4ECE6]/50 px-5 py-2 text-center"
              @click="$emit('cancelar')"
            >
              <span class="font-bold text-[#950606]">Não.</span>
              <span class="text-[#584237]">Cancelar este fluxo.</span>
            </button>
          </div>
        </div>
      </div>
    </template>
    <p v-else role="status" class="text-[#584237]">Aguardando o resultado da simulação da alternativa.</p>
  </section>
</template>
