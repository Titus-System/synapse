<script setup lang="ts">
import { ref, watch } from 'vue'
import { usarStoreSessao } from '@/stores/session'
import PortalAuditoria from '../components/PortalAuditoria.vue'
import { auditoriaApi } from '../services/auditoria.api'
import { useConsultaAuditoria } from '../composables/useConsultaAuditoria'
import { dataAuditoria } from '../composables/apresentacaoAuditoria'
import type { PaginaJobsAuditoria } from '../types'
const sessao = usarStoreSessao()
const pagina = ref(0)
const { dados, carregando, erro, carregar } =
  useConsultaAuditoria<PaginaJobsAuditoria>('listar_dossies')
function consultar() {
  return carregar((signal) => auditoriaApi.listar(pagina.value, 12, signal))
}
watch(pagina, consultar, { immediate: true })
</script>
<template>
  <PortalAuditoria :login="sessao.login" @sair="sessao.sair">
    <p class="mb-4 text-sm font-semibold text-[#a74700]">AUDITORIA · CONSULTA GLOBAL</p>
    <h1 class="font-serif text-3xl font-bold leading-tight text-[#2e1a10] sm:text-4xl xl:text-5xl">
      Dossiês de regras
    </h1>
    <p class="mb-10 mt-4">
      Consulte a entrada, as versões e os registros das regras de todos os usuários.
    </p>
    <p
      v-if="carregando"
      role="status"
      class="rounded-2xl border border-[#dec0b1] bg-white px-6 py-12 text-center shadow-sm"
    >
      Carregando dossiês…
    </p>
    <div
      v-else-if="erro"
      role="alert"
      class="rounded-2xl border border-[#dec0b1] bg-white px-6 py-12 text-center shadow-sm"
    >
      <p>{{ erro }}</p>
      <button
        class="mt-5 cursor-pointer rounded-lg bg-[#f87519] px-5 py-3 text-sm font-medium text-white transition hover:bg-[#dd620c] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
        @click="consultar"
      >
        Tentar novamente
      </button>
    </div>
    <section
      v-else-if="dados"
      class="overflow-hidden rounded-2xl border border-[#dec0b1] bg-white shadow-sm"
    >
      <div class="flex items-center justify-between gap-4 p-6">
        <h2 class="font-serif text-2xl font-bold">Dossiês encontrados</h2>
        <span>{{ dados.total }} resultados</span>
      </div>
      <p v-if="!dados.itens.length" class="p-8">Nenhum dossiê encontrado.</p>
      <div v-else class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead class="bg-[#fff0e9]">
            <tr>
              <th class="p-5">Regra / ID</th>
              <th class="p-5">Responsável</th>
              <th class="p-5">Status / origem</th>
              <th class="p-5">Competências</th>
              <th class="p-5">Criação / finalização</th>
              <th class="p-5">Detalhe</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="job in dados.itens"
              :key="job.id"
              class="border-t border-[#f1ded3] hover:bg-[#fff8f5]"
            >
              <td class="max-w-72 p-5">
                <strong class="block text-[#2e1a10]">{{ job.nome || 'Regra sem nome' }}</strong
                ><span class="mt-2 block break-all text-xs">{{ job.id }}</span>
              </td>
              <td class="p-5">{{ job.usuario.login }}</td>
              <td class="p-5">
                <span class="rounded-full bg-[#fff0e9] px-3 py-1">{{ job.status }}</span
                ><span class="mt-3 block">{{ job.origem }}</span>
              </td>
              <td class="p-5">{{ job.competencias.join(', ') || 'Não informadas' }}</td>
              <td class="p-5">
                <span class="block whitespace-nowrap">{{ dataAuditoria(job.criado_em) }}</span
                ><span class="mt-2 block whitespace-nowrap">{{
                  dataAuditoria(job.finalizado_em)
                }}</span>
              </td>
              <td class="p-5">
                <RouterLink
                  :to="{
                    name: 'auditoria-dossie',
                    params: { id: job.id },
                    query: { aba: 'regra' },
                  }"
                  class="inline-flex min-h-10 items-center whitespace-nowrap rounded-lg px-2 font-medium text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
                  >Consultar →</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <nav
        aria-label="Paginação dos dossiês"
        class="flex flex-wrap items-center justify-between gap-4 border-t border-[#f1ded3] p-6"
      >
        <span>Página {{ dados.pagina + 1 }} · {{ dados.total }} dossiês</span>
        <div class="flex gap-5">
          <button
            :disabled="pagina === 0"
            class="min-h-10 cursor-pointer rounded-lg px-3 text-sm text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700] disabled:cursor-default disabled:opacity-40"
            @click="pagina--"
          >
            ← Anterior</button
          ><button
            :disabled="(dados.pagina + 1) * dados.tamanho >= dados.total"
            class="min-h-10 cursor-pointer rounded-lg px-3 text-sm text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700] disabled:cursor-default disabled:opacity-40"
            @click="pagina++"
          >
            Próxima →
          </button>
        </div>
      </nav>
    </section>
  </PortalAuditoria>
</template>
