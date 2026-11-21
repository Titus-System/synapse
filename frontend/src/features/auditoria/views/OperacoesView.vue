<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  isNavigationFailure,
  NavigationFailureType,
  useRoute,
  useRouter,
  type LocationQueryRaw,
} from 'vue-router'
import { usarStoreSessao } from '@/stores/session'
import PortalAuditoria from '../components/PortalAuditoria.vue'
import FiltrosOperacoes from '../components/FiltrosOperacoes.vue'
import ContadoresOperacoes from '../components/ContadoresOperacoes.vue'
import TabelaEventos from '../components/TabelaEventos.vue'
import PaginacaoEventos from '../components/PaginacaoEventos.vue'
import { auditoriaApi } from '../services/auditoria.api'
import { useConsultaAuditoria } from '../composables/useConsultaAuditoria'
import {
  consultaDoFiltro,
  filtroDaRota,
  paginaDaRota,
  queryDoFiltro,
} from '../composables/filtrosOperacoes'
import type { FiltroPainel, FiltrosEventosAuditoria, PaginaEventosAuditoria } from '../types'
const TAMANHO = 12
const sessao = usarStoreSessao()
const route = useRoute()
const router = useRouter()
const { dados, carregando, erro, carregar } = useConsultaAuditoria<PaginaEventosAuditoria>(
  'listar_eventos_auditoria',
)
const {
  dados: opcoes,
  erro: erroOpcoes,
  carregar: carregarOpcoes,
} = useConsultaAuditoria<FiltrosEventosAuditoria>('consultar_filtros_auditoria')
const aplicado = computed(() => filtroDaRota(route.query))
const pagina = computed(() => paginaDaRota(route.query))
const rascunho = ref<FiltroPainel>({ ...aplicado.value })
function consultar() {
  const filtro = consultaDoFiltro(aplicado.value)
  const numero = pagina.value
  return carregar((signal) => auditoriaApi.listarEventos(filtro, numero, TAMANHO, signal))
}
function consultarOpcoes() {
  return carregarOpcoes((signal) => auditoriaApi.consultarFiltros(signal))
}
async function navegar(query: LocationQueryRaw) {
  const falha = await router.push({ query })
  // O mesmo endereço não muda a rota, mas aplicar de novo deve consultar de novo.
  if (isNavigationFailure(falha, NavigationFailureType.duplicated)) {
    rascunho.value = { ...aplicado.value }
    await consultar()
  }
}
function irParaPagina(numero: number) {
  return navegar(queryDoFiltro(aplicado.value, numero))
}
// Ao sair para o dossiê, a rota muda antes de a view ser desmontada; só o painel consulta.
watch(
  () => (route.name === 'auditoria-operacoes' ? route.fullPath : undefined),
  (caminho) => {
    if (caminho === undefined) return
    rascunho.value = { ...aplicado.value }
    void consultar()
  },
  { immediate: true },
)
void consultarOpcoes()
</script>
<template>
  <PortalAuditoria :login="sessao.login" secao="operacoes" @sair="sessao.sair">
    <p class="mb-4 text-sm font-semibold text-[#a74700]">AUDITORIA · CONSULTA GLOBAL</p>
    <h1 class="font-serif text-3xl font-bold leading-tight text-[#2e1a10] sm:text-4xl xl:text-5xl">
      Todas as operações
    </h1>
    <p class="mb-10 mt-4">
      Veja o que aconteceu nas regras de todos os usuários e abra o dossiê de cada evento.
    </p>
    <FiltrosOperacoes
      v-model="rascunho"
      :opcoes="opcoes"
      @aplicar="navegar(queryDoFiltro(rascunho))"
      @limpar="navegar({})"
    />
    <p v-if="erroOpcoes" role="alert" class="-mt-4 mb-8 flex flex-wrap items-center gap-3 text-sm">
      Não foi possível carregar as opções dos filtros.
      <button
        class="min-h-10 cursor-pointer rounded-lg px-2 font-medium text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
        @click="consultarOpcoes"
      >
        Tentar novamente
      </button>
    </p>
    <p
      v-if="carregando"
      role="status"
      class="rounded-2xl border border-[#dec0b1] bg-white px-6 py-12 text-center shadow-sm"
    >
      Carregando operações…
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
      <ContadoresOperacoes :contadores="dados.contadores" />
      <p
        class="mb-6 flex items-start gap-3 rounded-xl border border-[#f3d3c2] bg-[#fff0e9] px-4 py-3 text-sm"
      >
        <svg
          class="mt-0.5 size-4 shrink-0 text-[#a74700]"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5M12 8h.01" />
        </svg>
        Escopo global: eventos das regras de todos os usuários. Loja, marca e cargo são os da versão
        mais recente de cada regra.
      </p>
      <section class="overflow-hidden rounded-2xl border border-[#dec0b1] bg-white shadow-sm">
        <div class="flex items-center justify-between gap-4 p-6">
          <h2 class="font-serif text-2xl font-bold text-[#2e1a10]">Eventos</h2>
          <span class="text-sm text-[#806b5d]">{{ dados.total }} eventos</span>
        </div>
        <p v-if="!dados.itens.length" class="border-t border-[#f1ded3] p-8">
          Nenhum evento encontrado com estes filtros.
        </p>
        <TabelaEventos v-else :eventos="dados.itens" />
        <PaginacaoEventos
          :pagina="dados.pagina"
          :tamanho="dados.tamanho"
          :total="dados.total"
          :quantidade="dados.itens.length"
          @ir="irParaPagina"
        />
      </section>
    </template>
  </PortalAuditoria>
</template>
