<script setup lang="ts">
import { dataCivilAuditoria } from '../composables/apresentacaoAuditoria'
import type { FontesResultadoAuditoria } from '../types'
defineProps<{ fontes?: FontesResultadoAuditoria }>()
</script>
<template>
  <div class="mt-6" data-fontes>
    <h3 class="mb-3 font-serif text-lg font-bold">Fontes dos dados</h3>
    <p v-if="!fontes" class="text-sm" data-sem-fontes>Sem fontes registradas para este resultado.</p>
    <template v-else>
      <dl class="grid gap-4 text-sm sm:grid-cols-3">
        <div>
          <dt class="text-[#806b5d]">Versão das bases</dt>
          <dd class="font-semibold" data-versao-bases>v{{ fontes.manifesto.versao }}</dd>
        </div>
        <div>
          <dt class="text-[#806b5d]">Congelamento</dt>
          <dd class="font-semibold">{{ dataCivilAuditoria(fontes.manifesto.congelamento) }}</dd>
        </div>
        <div>
          <dt class="text-[#806b5d]">Competências processadas</dt>
          <dd class="font-semibold">{{ fontes.competencias.join(', ') }}</dd>
        </div>
      </dl>
      <div class="mt-4 grid items-start gap-3 lg:grid-cols-2">
        <details class="rounded-lg border border-[#dec0b1] p-3" data-arquivos>
          <summary class="cursor-pointer font-semibold">
            Arquivos de base ({{ fontes.arquivos.length }})
          </summary>
          <ul class="mt-2 space-y-3 text-sm">
            <li v-for="arquivo in fontes.arquivos" :key="arquivo.nome">
              <p class="break-all font-semibold">{{ arquivo.nome }}</p>
              <p class="break-all font-mono text-xs text-[#806b5d]">sha256 {{ arquivo.sha256 }}</p>
            </li>
          </ul>
        </details>
        <details class="rounded-lg border border-[#dec0b1] p-3" data-baselines>
          <summary class="cursor-pointer font-semibold">
            Baselines por competência ({{ fontes.baselines.length }})
          </summary>
          <ul class="mt-2 space-y-3 text-sm">
            <li
              v-for="baseline in fontes.baselines"
              :key="`${baseline.competencia}-${baseline.arquivo}`"
              :data-baseline="baseline.competencia"
            >
              <p class="font-semibold">{{ baseline.competencia }}</p>
              <p class="break-all">{{ baseline.arquivo }}</p>
              <p class="break-all font-mono text-xs text-[#806b5d]">sha256 {{ baseline.sha256 }}</p>
            </li>
          </ul>
        </details>
      </div>
    </template>
  </div>
</template>
