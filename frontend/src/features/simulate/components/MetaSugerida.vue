<script setup lang="ts">
import type { MetaSugerida } from '@/types/api'
import { formatarReais } from '@/composables/apresentacaoDetalhamento'

defineProps<{ sugestao: MetaSugerida; processando: boolean; podeAceitar: boolean }>()
defineEmits<{ aceitar: [] }>()
</script>

<template>
  <section
    aria-labelledby="titulo-meta-sugerida"
    class="mx-auto mb-12 w-full max-w-6xl px-4 sm:px-6 lg:px-10"
  >
    <h2 id="titulo-meta-sugerida" class="mb-3 text-3xl font-semibold text-[#2B160D]">
      Meta de vendas sugerida
    </h2>
    <div class="rounded-lg border-2 border-[#DFC0B2] bg-[#F4ECE6]/50 p-5 text-[#584237]">
      <p v-if="'sem_solucao' in sugestao" role="status">
        Não encontramos uma meta maior para sugerir. Você pode continuar com o resultado da
        simulação atual.
      </p>
      <template v-else>
        <p class="mb-4">
          Encontramos uma meta maior que cabe no seu orçamento. Confira a comissão simulada nessa
          meta.
        </p>
        <dl class="grid gap-4 sm:grid-cols-3">
          <div
            v-for="campo in [
              { rotulo: 'Meta de vendas sugerida', valor: sugestao.meta_venda },
              { rotulo: 'Comissão na meta sugerida', valor: sugestao.total_simulado },
              { rotulo: 'Orçamento de comissão', valor: sugestao.orcamento },
            ]"
            :key="campo.rotulo"
            class="min-w-0 rounded-lg bg-[#FFE9E1] p-4"
          >
            <dt class="mb-2">{{ campo.rotulo }}</dt>
            <dd class="break-words text-xl font-bold text-[#2B160D]">
              {{ formatarReais(campo.valor) }}
            </dd>
          </div>
        </dl>
        <button
          type="button"
          :disabled="!podeAceitar || processando"
          :aria-busy="processando"
          class="mt-5 cursor-pointer rounded-lg bg-[#c2560b] px-6 py-3 text-white disabled:cursor-wait disabled:opacity-60"
          @click="$emit('aceitar')"
        >
          {{ processando ? 'Aceitando meta...' : 'Aceitar meta sugerida' }}
        </button>
      </template>
    </div>
  </section>
</template>
