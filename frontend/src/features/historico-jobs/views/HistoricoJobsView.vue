<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TheSidebar from '@/components/TheSidebar.vue'
import ControlesRepositorio from '../components/ControlesRepositorio.vue'
import LinhaRegraHistorico from '../components/LinhaRegraHistorico.vue'
import { useHistoricoPaginado } from '../composables/useHistoricoPaginado'
import type { TipoDeHistorico } from '../types'

const rota = useRoute()
const roteador = useRouter()
const tipo = computed<TipoDeHistorico>(() =>
  rota.name === 'regras-arquivadas' ? 'arquivadas' : 'salvas',
)
const arquivadas = computed(() => tipo.value === 'arquivadas')
const {
  pagina,
  carregando,
  erro,
  cartoes,
  totais,
  total,
  paginas,
  numeros,
  primeira,
  ultima,
  carregar,
  irParaPagina,
} = useHistoricoPaginado(tipo)
function detalhes(id: string) {
  void roteador.push({ name: 'finalizar', params: { id } })
}
function reprocessar(id: string) {
  void roteador.push({ name: 'nova-regra', query: { reprocessar: id } })
}
</script>

<template>
  <div
    class="tela-de-negocio min-h-[100dvh] bg-[#fff8f5] text-[#2e1a10] lg:grid lg:h-[100dvh] lg:grid-cols-[16rem_minmax(0,1fr)] lg:overflow-hidden xl:grid-cols-[20rem_minmax(0,1fr)]"
  >
    <TheSidebar
      class="hidden lg:flex"
      repositorio
      :secao-ativa="tipo"
      :quantidade-salvas="totais.salvas"
      :quantidade-arquivadas="totais.arquivadas"
    />
    <main class="min-w-0 lg:min-h-0 lg:overflow-y-auto">
      <header
        class="flex min-h-20 items-center justify-between gap-4 border-b border-[#dec0b1] px-6 text-[#644b3e] lg:px-8"
      >
        <span class="text-base">Repositório</span>
        <span class="flex items-center gap-3 text-sm font-semibold">
          <svg
            class="size-5 text-[#a74700]"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            aria-hidden="true"
          >
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
          <span class="rounded-full bg-[#fff0e9] px-4 py-2">Acesso às regras</span>
        </span>
      </header>
      <nav class="flex gap-5 px-6 pt-5 text-sm lg:hidden" aria-label="Navegação de regras">
        <RouterLink to="/nova-regra" class="text-[#a74700]">+ Nova Regra</RouterLink>
        <RouterLink to="/salvas" class="text-[#644b3e]">Regras Salvas</RouterLink>
      </nav>
      <section class="mx-auto max-w-[90rem] px-4 pb-14 pt-12 sm:px-8 lg:px-12 lg:pt-16 xl:px-16">
        <div class="mb-12 text-center lg:mb-16">
          <p
            class="mb-4 flex items-center justify-center gap-2 text-xs font-medium tracking-wide text-[#644b3e] sm:text-sm"
          >
            <span
              class="grid size-7 place-items-center rounded-full bg-[#f3e8df] text-[#a74700]"
              aria-hidden="true"
              >▣</span
            >
            REPOSITÓRIO CORPORATIVO
          </p>
          <h1 class="font-serif text-3xl font-bold leading-tight sm:text-4xl xl:text-5xl">
            Regras de Negócio {{ arquivadas ? 'Arquivadas' : 'Salvas' }}
          </h1>
        </div>

        <ControlesRepositorio :total="totais[tipo]" />

        <div class="overflow-hidden rounded-2xl bg-white shadow-sm" :aria-busy="carregando">
          <div
            class="hidden grid-cols-[minmax(0,1fr)_minmax(10rem,.55fr)_auto] gap-6 bg-[#fff0e9] px-8 py-5 text-sm font-medium tracking-wide text-[#644b3e] lg:grid"
            aria-hidden="true"
          >
            <span>REGRA &amp; CONTEXTO</span><span>DATA</span><span>ACESSO</span>
          </div>
          <div v-if="carregando" role="status" class="space-y-7 px-8 py-10">
            <span class="sr-only">Carregando regras…</span>
            <div v-for="n in 5" :key="n" class="h-16 animate-pulse rounded-xl bg-[#fbf1eb]"></div>
          </div>
          <div v-else-if="erro" role="alert" class="px-6 py-14 text-center">
            <p>{{ erro }}</p>
            <button
              type="button"
              class="mt-5 cursor-pointer rounded-lg bg-[#f87519] px-5 py-3 font-medium text-white hover:bg-[#dd620c]"
              @click="carregar()"
            >
              Tentar novamente
            </button>
          </div>
          <div v-else-if="cartoes.length === 0" class="px-6 py-16 text-center" role="status">
            <h2 class="font-serif text-2xl font-semibold">
              Nenhuma regra {{ arquivadas ? 'arquivada' : 'salva' }} ainda
            </h2>
            <p class="mt-3 text-sm text-[#806b5d]">
              As regras {{ arquivadas ? 'arquivadas' : 'salvas' }} aparecerão aqui.
            </p>
          </div>
          <template v-else>
            <LinhaRegraHistorico
              v-for="cartao in cartoes"
              :key="cartao.resumo.id"
              :cartao="cartao"
              :arquivada="arquivadas"
              @detalhes="detalhes(cartao.resumo.id)"
              @reprocessar="reprocessar(cartao.resumo.id)"
            />
            <div class="flex flex-wrap items-center justify-between gap-5 px-6 py-7 sm:px-8">
              <p class="text-sm text-[#644b3e]">
                Mostrando
                <strong class="font-medium text-[#2e1a10]">{{ primeira }}–{{ ultima }}</strong> de
                {{ total }} regras catalogadas
              </p>
              <nav class="flex items-center gap-1" aria-label="Paginação do histórico">
                <button
                  type="button"
                  aria-label="Primeira página"
                  :disabled="pagina === 0"
                  class="size-9 cursor-pointer rounded-lg text-[#8d7566] hover:bg-[#fff0e9] disabled:cursor-default disabled:opacity-35"
                  @click="irParaPagina(0)"
                >
                  «
                </button>
                <button
                  type="button"
                  aria-label="Página anterior"
                  :disabled="pagina === 0"
                  class="size-9 cursor-pointer rounded-lg text-[#8d7566] hover:bg-[#fff0e9] disabled:cursor-default disabled:opacity-35"
                  @click="irParaPagina(pagina - 1)"
                >
                  ‹
                </button>
                <button
                  v-for="numero in numeros"
                  :key="numero"
                  type="button"
                  :aria-label="`Página ${numero + 1}`"
                  :aria-current="pagina === numero ? 'page' : undefined"
                  class="size-10 cursor-pointer rounded-xl text-sm"
                  :class="
                    pagina === numero
                      ? 'bg-[#f87519] font-semibold text-white'
                      : 'hover:bg-[#fff0e9]'
                  "
                  @click="irParaPagina(numero)"
                >
                  {{ numero + 1 }}
                </button>
                <button
                  type="button"
                  aria-label="Próxima página"
                  :disabled="pagina + 1 >= paginas"
                  class="size-9 cursor-pointer rounded-lg text-[#8d7566] hover:bg-[#fff0e9] disabled:cursor-default disabled:opacity-35"
                  @click="irParaPagina(pagina + 1)"
                >
                  ›
                </button>
                <button
                  type="button"
                  aria-label="Última página"
                  :disabled="pagina + 1 >= paginas"
                  class="size-9 cursor-pointer rounded-lg text-[#8d7566] hover:bg-[#fff0e9] disabled:cursor-default disabled:opacity-35"
                  @click="irParaPagina(paginas - 1)"
                >
                  »
                </button>
              </nav>
            </div>
          </template>
        </div>
      </section>
    </main>
  </div>
</template>
