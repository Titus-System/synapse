<script setup lang="ts">
import type { MetaSugerida, MotivoMetaSemSolucao } from '@/types/api'
import { formatarReais } from '@/composables/apresentacaoDetalhamento'

defineProps<{
  sugestao?: MetaSugerida
  buscando: boolean
  podeAceitar: boolean
  processando: boolean
  erro: string | null
}>()
defineEmits<{ aceitar: [] }>()

const motivos: Record<MotivoMetaSemSolucao, string> = {
  nao_monotonica: 'Os resultados não permitiram confirmar uma meta maior com segurança.',
  intervalo_esgotado: 'A busca chegou ao limite de tentativas sem confirmar uma meta maior.',
  falha_execucao: 'Não foi possível concluir uma das simulações da busca.',
}
</script>

<template>
  <section
    aria-labelledby="titulo-meta-sugerida"
    class="mx-auto mb-12 w-full max-w-6xl px-4 sm:px-6 lg:px-10"
  >
    <h2 id="titulo-meta-sugerida" class="mb-3 text-3xl font-semibold text-[#2B160D]">
      Sugestão de meta de vendas
    </h2>
    <p v-if="buscando" role="status" class="rounded-lg border border-[#DFC0B2] p-5 text-[#584237]">
      Estamos buscando uma meta de vendas maior dentro do orçamento. Você pode aguardar a sugestão
      ou seguir com a meta atual.
    </p>
    <div
      v-else-if="sugestao && 'meta_venda' in sugestao"
      class="rounded-lg border border-[#14532D]/20 border-l-8 border-l-[#14532D] bg-[#F4ECE6]/50 p-5"
    >
      <p class="mb-5 font-bold text-[#14532D]">
        Encontramos uma meta de vendas maior que cabe no orçamento.
      </p>
      <dl class="grid gap-5 sm:grid-cols-3">
        <div>
          <dt class="mb-1 text-[#584237]">Meta de vendas sugerida</dt>
          <dd class="rounded-lg border border-[#DFC0B2] bg-[#FFE9E1] px-3.5 py-3">
            {{ formatarReais(sugestao.meta_venda) }}
          </dd>
        </div>
        <div>
          <dt class="mb-1 text-[#584237]">Comissão simulada nessa meta</dt>
          <dd class="rounded-lg border border-[#DFC0B2] bg-[#FFE9E1] px-3.5 py-3">
            {{ formatarReais(sugestao.total_simulado) }}
          </dd>
        </div>
        <div>
          <dt class="mb-1 text-[#584237]">Orçamento de comissão</dt>
          <dd class="rounded-lg border border-[#DFC0B2] bg-[#FFE9E1] px-3.5 py-3">
            {{ formatarReais(sugestao.orcamento) }}
          </dd>
        </div>
      </dl>
      <p class="mt-5 text-[#584237]">
        Essa meta já foi simulada com os mesmos percentuais e condições da regra. Você pode manter a
        meta atual ou usar a sugestão antes de finalizar.
      </p>
      <button
        type="button"
        :disabled="!podeAceitar"
        :aria-busy="processando"
        class="mt-4 cursor-pointer rounded-lg bg-[#14532D] px-6 py-3 text-white disabled:cursor-not-allowed disabled:opacity-60"
        @click="$emit('aceitar')"
      >
        {{ processando ? 'Aplicando meta...' : 'Usar meta sugerida' }}
      </button>
    </div>
    <div
      v-else-if="sugestao && 'sem_solucao' in sugestao"
      role="status"
      class="rounded-lg border border-[#DFC0B2] p-5 text-[#584237]"
    >
      <p>A busca automática não confirmou uma meta de vendas maior.</p>
      <p class="mt-2">{{ motivos[sugestao.sem_solucao.motivo] }}</p>
      <p class="mt-2">A simulação e a meta atuais continuam disponíveis para finalização.</p>
    </div>
    <p v-if="erro" role="alert" class="mt-4 text-[#950606]">{{ erro }}</p>
  </section>
</template>
