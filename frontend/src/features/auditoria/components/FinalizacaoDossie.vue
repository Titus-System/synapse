<script setup lang="ts">
import { acaoDeFinalizacao, dataAuditoria } from '../composables/apresentacaoAuditoria'
import type { Finalizacao } from '../composables/simulacoesDossie'
defineProps<{ finalizacao?: Finalizacao; versaoVigente?: number }>()
</script>
<template>
  <section
    class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8"
    aria-label="Finalização da regra"
  >
    <p class="text-xs font-semibold tracking-wide text-[#a74700]">FINALIZAÇÃO</p>
    <h2 class="mb-6 mt-3 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
      Como a regra foi finalizada
    </h2>
    <p v-if="!finalizacao" role="status">Nenhuma ação de fechamento registrada.</p>
    <dl v-else class="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
      <div>
        <dt class="text-[#806b5d]">Ação de fechamento</dt>
        <dd class="font-semibold" :title="finalizacao.acao.acao" data-acao>
          {{ acaoDeFinalizacao(finalizacao.acao.acao) }}
        </dd>
      </div>
      <div>
        <dt class="text-[#806b5d]">Data e hora</dt>
        <dd class="font-semibold">{{ dataAuditoria(finalizacao.acao.executado_em) }}</dd>
      </div>
      <div>
        <dt class="text-[#806b5d]">Versão vigente</dt>
        <dd class="font-semibold" data-versao>
          {{ versaoVigente != null ? `v${versaoVigente}` : 'Não informada' }}
        </dd>
      </div>
      <div>
        <dt class="text-[#806b5d]">Meta sugerida</dt>
        <dd class="font-semibold" data-aceite>
          {{
            finalizacao.aceite?.aceita_em
              ? `Aceita em ${dataAuditoria(finalizacao.aceite.aceita_em)}`
              : 'Sem aceite registrado'
          }}
        </dd>
      </div>
    </dl>
  </section>
</template>