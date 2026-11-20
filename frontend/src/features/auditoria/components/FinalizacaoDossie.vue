<script setup lang="ts">
import { computed } from 'vue'
import {
  acaoDeFinalizacao,
  codigosAuditoria,
  dataAuditoria,
  listaAuditoria,
  vigenciaAuditoria,
} from '../composables/apresentacaoAuditoria'
import type { EvidenciasVersao, Finalizacao } from '../composables/simulacoesDossie'
import IdCopiavel from './IdCopiavel.vue'
const props = defineProps<{
  finalizacao?: Finalizacao
  versaoVigente?: number
  evidencias?: EvidenciasVersao
  regra: string
  responsavel: string
}>()
const nucleo = computed(() => props.evidencias?.versao.representacao.nucleo)
const simulacoes = computed(() => {
  const numeros = props.evidencias?.simulacoes ?? []
  if (!numeros.length) return 'nenhuma simulação'
  return `${numeros.length === 1 ? 'simulação' : 'simulações'} ${listaAuditoria(numeros.map(String))}`
})
</script>
<template>
  <section
    class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8"
    aria-label="Finalização da regra"
  >
    <p class="text-xs font-semibold tracking-wide text-[#a74700]">
      FINALIZAÇÃO<template v-if="versaoVigente != null">
        · VERSÃO VIGENTE <span data-versao>v{{ versaoVigente }}</span></template
      >
    </p>
    <h2 class="mb-6 mt-3 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
      Como a regra foi finalizada
    </h2>
    <p v-if="!finalizacao" role="status">Nenhuma ação de fechamento registrada.</p>
    <template v-else>
      <p
        class="inline-block break-all rounded-full bg-[#e4f2e7] px-3 py-1 text-xs font-semibold text-[#22683a]"
        data-finalizada-por
      >
        Finalizada por {{ responsavel }}
      </p>
      <h3 class="mt-4 break-words font-serif text-xl font-bold text-[#2e1a10]" data-nome-regra>
        {{ regra }}
      </h3>
      <dl class="mt-5 grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <dt class="text-[#806b5d]">Loja / marca · códigos</dt>
          <dd class="font-semibold" data-escopo>
            {{ codigosAuditoria(nucleo?.loja) }} / {{ codigosAuditoria(nucleo?.marca) }}
          </dd>
        </div>
        <div>
          <dt class="text-[#806b5d]">Vigência</dt>
          <dd class="font-semibold" data-vigencia>{{ vigenciaAuditoria(nucleo?.vigencia) }}</dd>
        </div>
        <div>
          <dt class="text-[#806b5d]">Ação de fechamento</dt>
          <dd class="font-semibold" :title="finalizacao.acao.acao" data-acao>
            {{ acaoDeFinalizacao(finalizacao.acao.acao) }}
          </dd>
        </div>
        <div>
          <dt class="text-[#806b5d]">Finalização registrada</dt>
          <dd class="break-all font-semibold" data-registrada>
            {{ dataAuditoria(finalizacao.acao.executado_em) }} · {{ responsavel }}
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
        <div class="sm:col-span-2">
          <dt class="text-[#806b5d]">Evidências vinculadas</dt>
          <dd class="font-semibold" data-evidencias>
            <template v-if="evidencias">
              v{{ evidencias.versao.versao }} ·
              <template v-for="codigo in evidencias.codigos" :key="codigo.id">
                código
                <IdCopiavel :id="codigo.id" rotulo="do código da versão vigente" somente-botao /> ·
              </template>
              {{ simulacoes }}
            </template>
            <template v-else>Não informadas</template>
          </dd>
        </div>
      </dl>
    </template>
  </section>
</template>
