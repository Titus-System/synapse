<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { usarStoreSessao } from '@/stores/session'
import PortalAuditoria from '../components/PortalAuditoria.vue'
import RegraVersoes from '../components/RegraVersoes.vue'
import TrilhaDossie from '../components/TrilhaDossie.vue'
import { auditoriaApi } from '../services/auditoria.api'
import { exportarDossie } from '../services/exportarDossie'
import { useConsultaAuditoria } from '../composables/useConsultaAuditoria'
import { dataAuditoria, codigosAuditoria } from '../composables/apresentacaoAuditoria'
import { trilhaCronologica } from '../composables/trilhaDossie'
import type { RegistroAuditoria, AbaDossie, EventoAuditoria } from '../types'
import ConversaPython from '../components/ConversaPython.vue'
const sessao = usarStoreSessao()
const route = useRoute()
const router = useRouter()
const { dados, carregando, erro, carregar } =
  useConsultaAuditoria<RegistroAuditoria>('consultar_dossie')
const {
  dados: trilha,
  carregando: carregandoTrilha,
  erro: erroTrilha,
  carregar: carregarTrilha,
} = useConsultaAuditoria<EventoAuditoria[]>('listar_trilha_dossie')
let trilhaDoJob: string | undefined
const falhaExportacao = ref(false)
const abas: { id: AbaDossie; nome: string }[] = [
  { id: 'regra', nome: 'Regra e versões' },
  { id: 'conversa', nome: 'Conversa e Python' },
  { id: 'simulacoes', nome: 'Simulações e finalização' },
]
const aba = computed(() =>
  abas.some((item) => item.id === route.query.aba) ? route.query.aba : 'regra',
)
const ultima = computed(() =>
  dados.value ? [...dados.value.versoes].sort((a, b) => b.versao - a.versao)[0] : undefined,
)
// Quem chegou pelo painel volta a ele com os mesmos filtros, que estão no endereço anterior.
const voltar = computed(() => {
  const anterior = route.fullPath && router.options.history.state.back
  return typeof anterior === 'string' && router.resolve(anterior).name === 'auditoria-operacoes'
    ? { para: anterior, nome: 'Todas as operações' }
    : { para: '/auditoria/dossies', nome: 'Dossiês de regras' }
})
function consultar() {
  const id = String(route.params.id)
  falhaExportacao.value = false
  return carregar((signal) => auditoriaApi.obter(id, signal), id)
}
function consultarTrilha() {
  const id = String(route.params.id)
  trilhaDoJob = id
  return carregarTrilha(
    (signal) =>
      trilhaCronologica((pagina) => auditoriaApi.listarEventos({ regra: id }, pagina, 100, signal)),
    id,
  )
}
function selecionar(id: AbaDossie) {
  return router.replace({ query: { ...route.query, aba: id } })
}
function exportar() {
  if (!dados.value) return
  try {
    exportarDossie(dados.value)
    falhaExportacao.value = false
  } catch {
    falhaExportacao.value = true
  }
}
watch(() => route.params.id, consultar, { immediate: true })
watch(
  [() => route.params.id, aba],
  ([id, atual]) => {
    if (atual === 'simulacoes' && id !== undefined && String(id) !== trilhaDoJob)
      void consultarTrilha()
  },
  { immediate: true },
)
</script>
<template>
  <PortalAuditoria :login="sessao.login" :regra="dados?.job.nome || undefined" @sair="sessao.sair">
    <div class="mb-8 flex flex-wrap items-center justify-between gap-4">
      <RouterLink :to="voltar.para" class="font-semibold text-[#a74700]"
        >← {{ voltar.nome }}</RouterLink
      ><button
        v-if="dados"
        class="cursor-pointer rounded-lg border border-[#a74700] bg-white px-5 py-3 text-sm font-semibold text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
        @click="exportar"
      >
        Exportar dossiê ↓
      </button>
    </div>
    <p v-if="falhaExportacao" role="alert" class="mb-5">
      Não foi possível exportar o dossiê. Tente novamente.
    </p>
    <p
      v-if="carregando"
      role="status"
      class="rounded-2xl border border-[#dec0b1] bg-white px-6 py-12 text-center shadow-sm"
    >
      Carregando dossiê…
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
    <template v-else-if="dados">
      <div class="mb-5 flex flex-wrap gap-3 text-sm">
        <span class="break-all rounded-full bg-[#fff0e9] px-4 py-2 text-[#a74700]">{{
          dados.job.id
        }}</span
        ><span class="rounded-full bg-[#fff0e9] px-4 py-2"
          >{{ dados.job.status }}<template v-if="ultima"> · v{{ ultima.versao }}</template></span
        >
      </div>
      <h1
        class="break-words font-serif text-3xl font-bold leading-tight text-[#2e1a10] sm:text-4xl xl:text-5xl"
      >
        {{ dados.job.nome || 'Regra sem nome' }}
      </h1>
      <p class="mt-4">Histórico integral, da entrada original à finalização.</p>
      <dl class="my-9 grid gap-6 text-sm sm:grid-cols-2 xl:grid-cols-4">
        <div>
          <dt class="mb-2 text-[#806b5d]">Responsável</dt>
          <dd class="break-all font-semibold">{{ dados.job.usuario.login }}</dd>
        </div>
        <div>
          <dt class="mb-2 text-[#806b5d]">Loja / marca · códigos</dt>
          <dd class="font-semibold">
            {{ codigosAuditoria(ultima?.representacao.nucleo.loja) }} /
            {{ codigosAuditoria(ultima?.representacao.nucleo.marca) }}
          </dd>
        </div>
        <div>
          <dt class="mb-2 text-[#806b5d]">Criação</dt>
          <dd class="font-semibold">{{ dataAuditoria(dados.job.criado_em) }}</dd>
        </div>
        <div>
          <dt class="mb-2 text-[#806b5d]">Finalização</dt>
          <dd class="font-semibold">{{ dataAuditoria(dados.job.finalizado_em) }}</dd>
        </div>
      </dl>
      <nav aria-label="Seções do dossiê" class="mb-7 grid grid-cols-3 border-b border-[#dec0b1]">
        <button
          v-for="item in abas"
          :key="item.id"
          :aria-current="aba === item.id ? 'page' : undefined"
          :class="
            aba === item.id ? 'border-[#a74700] font-semibold text-[#a74700]' : 'border-transparent'
          "
          class="cursor-pointer border-b-2 px-2 py-4 text-xs transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700] sm:text-sm"
          @click="selecionar(item.id)"
        >
          {{ item.nome }}
        </button>
      </nav>
      <RegraVersoes v-if="aba === 'regra'" :registro="dados" />
      <ConversaPython v-else-if="aba === 'conversa'" :registro="dados" />
      <TrilhaDossie
        v-else-if="aba === 'simulacoes'"
        :eventos="trilha"
        :carregando="carregandoTrilha"
        :erro="erroTrilha"
        @tentar-novamente="consultarTrilha"
      />
      <section v-else class="rounded-xl border border-[#dec0b1] bg-white p-9">
        <h2 class="mb-4 font-serif text-2xl font-bold">
          {{ abas.find((item) => item.id === aba)?.nome }}
        </h2>
        <p>Esta seção ainda não está disponível.</p>
      </section>
      <div class="mt-8 flex justify-end">
        <RouterLink
          :to="voltar.para"
          class="rounded-lg border border-[#dec0b1] bg-white px-5 py-3 text-sm font-semibold text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
          >← {{ voltar.nome }}</RouterLink
        >
      </div>
    </template>
  </PortalAuditoria>
</template>
