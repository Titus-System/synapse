<script setup lang="ts">
import { dataAuditoria, nomeDoNo } from '../composables/apresentacaoAuditoria'
import type { ChamadaModeloAuditoria } from '../types'
import BlocoTextoAuditoria from './BlocoTextoAuditoria.vue'
defineProps<{ chamada: ChamadaModeloAuditoria }>()
</script>
<template>
  <details class="rounded-xl border border-[#dec0b1] bg-white px-4 py-3 text-sm" data-chamada>
    <summary
      class="cursor-pointer font-semibold text-[#a74700] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
    >
      <span :title="chamada.no">{{ nomeDoNo(chamada.no) }}</span> · <span>{{ chamada.modelo.modelo }}</span> ·
      <span>{{ dataAuditoria(chamada.criado_em) }}</span> ·
      <span data-tokens>
        <template v-if="chamada.resposta?.consumo_tokens">
          {{ chamada.resposta.consumo_tokens.tokens_in }} tokens de entrada ·
          {{ chamada.resposta.consumo_tokens.tokens_out }} de saída
        </template>
        <template v-else>Consumo não informado</template>
      </span>
    </summary>
    <p class="mt-3 text-xs text-[#806b5d]">
      {{ chamada.modelo.provedor }} · versão {{ chamada.modelo.versao }}
      <template v-if="chamada.resposta?.consumo_tokens?.custo_usd != null">
        · custo US$ {{ chamada.resposta.consumo_tokens.custo_usd }}
      </template>
    </p>
    <BlocoTextoAuditoria titulo="Prompt" :texto="chamada.prompt" />
    <BlocoTextoAuditoria v-if="chamada.resposta" titulo="Resposta" :texto="chamada.resposta.texto" />
    <p v-else class="mt-3">Resposta não registrada.</p>
  </details>
</template>