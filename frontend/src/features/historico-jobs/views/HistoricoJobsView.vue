<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import TheProcessHeader from '@/components/TheProcessHeader.vue'
import TheSidebar from '@/components/TheSidebar.vue'
import type { JobResumo, StatusJob, Veredito } from '@/types/api'
import { listarTodosOsJobs } from '../services/historicoJobs.api'
import type { TipoDeHistorico } from '../types'

const tamanhoDaPagina = 6
const rota = useRoute()
const carregando = ref(false)
const mensagemDeErro = ref('')
const paginaAtual = ref(0)
const resumosDosJobs = ref<JobResumo[]>([])

const tipoDoHistorico = computed<TipoDeHistorico>(() =>
  rota.name === 'regras-arquivadas' ? 'arquivadas' : 'salvas',
)
const titulo = computed(() => (tipoDoHistorico.value === 'arquivadas' ? 'Arquivadas' : 'Salvas'))
const jobsArquivados = computed(() => resumosDosJobs.value.filter((resumoDoJob) => resumoDoJob.status === 'arquivado'))
const jobsSalvos = computed(() => resumosDosJobs.value.filter((resumoDoJob) => resumoDoJob.status !== 'arquivado'))
const jobsDoHistorico = computed(() =>
  tipoDoHistorico.value === 'arquivadas' ? jobsArquivados.value : jobsSalvos.value,
)
const quantidadeDePaginas = computed(() => Math.max(1, Math.ceil(jobsDoHistorico.value.length / tamanhoDaPagina)))
const jobsDaPagina = computed(() => {
  const inicio = paginaAtual.value * tamanhoDaPagina
  return jobsDoHistorico.value.slice(inicio, inicio + tamanhoDaPagina)
})
const regrasRecentes = computed(() =>
  resumosDosJobs.value.slice(0, 6).map((resumoDoJob) => ({
    identificador: resumoDoJob.id,
    rotulo: criarRotuloDaRegra(resumoDoJob),
  })),
)

function criarRotuloDaRegra(resumoDoJob: JobResumo): string {
  const data = new Date(resumoDoJob.criado_em).toLocaleDateString('pt-BR')
  return `Regra · ${data}`
}

function formatarCompetencias(competencias: readonly string[]): string {
  return competencias.map((competencia) => {
    const [ano, mes] = competencia.split('-')
    return ano && mes ? `${mes}/${ano}` : competencia
  }).join(' · ')
}

function nomearStatus(status: StatusJob): string {
  const nomes: Record<StatusJob, string> = {
    aguardando_transcricao: 'Aguardando transcrição',
    aguardando_confirmacao_parametros: 'Aguardando confirmação',
    gerando_regra: 'Gerando regra',
    simulando: 'Em simulação',
    simulacao_inviavel: 'Simulação inviável',
    aguardando_decisao_usuario: 'Aguardando decisão',
    liberado: 'Liberado',
    cancelado: 'Cancelado',
    arquivado: 'Arquivado',
    erro: 'Processamento com erro',
  }
  return nomes[status]
}

function nomearVeredito(veredito: Veredito | undefined): string {
  const nomes: Record<Veredito, string> = {
    viavel: 'Viável',
    inviavel: 'Inviável',
    indeterminado: 'Indeterminado',
  }
  return veredito ? nomes[veredito] : 'Ainda não disponível'
}

function irParaPagina(numeroDaPagina: number): void {
  if (numeroDaPagina < 0 || numeroDaPagina >= quantidadeDePaginas.value) return
  paginaAtual.value = numeroDaPagina
}

async function carregarHistorico(): Promise<void> {
  carregando.value = true
  mensagemDeErro.value = ''
  paginaAtual.value = 0

  try {
    resumosDosJobs.value = await listarTodosOsJobs()
  } catch {
    resumosDosJobs.value = []
    mensagemDeErro.value = 'Não foi possível carregar o histórico agora. Tente novamente em alguns instantes.'
  } finally {
    carregando.value = false
  }
}

watch(
  () => rota.name,
  () => {
    void carregarHistorico()
  },
  { immediate: true },
)
</script>

<template>
  <div class="min-h-screen bg-[#fdf7f3] text-[#2e1a10] md:grid md:grid-cols-[clamp(13.5rem,18vw,16.25rem)_1fr]">
    <TheSidebar
      class="hidden md:flex"
      :secao-ativa="tipoDoHistorico"
      :quantidade-arquivadas="jobsArquivados.length"
      :quantidade-salvas="jobsSalvos.length"
      :regras-recentes="regrasRecentes"
    />

    <main class="min-w-0 bg-[radial-gradient(circle_at_top,#fffdfb_0%,#fdf7f3_48%,#f8eee8_100%)]">
      <TheProcessHeader />

      <section class="mx-auto w-full max-w-6xl px-6 py-10 lg:px-10 lg:py-14">
        <div class="border-b border-[#eadbd2] pb-6">
          <div class="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
            <div class="shrink-0">
              <p class="text-xs font-semibold tracking-[0.14em] text-[#a54809] uppercase">Histórico de regras</p>
              <div class="mt-2 flex flex-wrap items-center gap-3">
                <h1 class="font-serif text-4xl font-semibold tracking-tight text-[#2e1a10]">{{ titulo }}</h1>
                <span class="rounded-full border border-[#ead4c7] bg-white/80 px-3 py-1 text-xs font-medium text-[#80695c]">
                  {{ jobsDoHistorico.length }} {{ jobsDoHistorico.length === 1 ? 'regra' : 'regras' }}
                </span>
              </div>
              <p class="mt-2 text-sm text-[#6b564a]">
                {{ tipoDoHistorico === 'arquivadas' ? 'Regras preservadas para consulta e reprocessamento futuro.' : 'Regras que permanecem disponíveis para acompanhamento.' }}
              </p>
            </div>

            <div class="flex w-full max-w-2xl gap-2" aria-label="Busca e filtro do histórico indisponíveis">
              <label class="relative block min-w-0 flex-1">
            <span class="sr-only">Pesquisar no histórico</span>
            <svg class="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-[#ae5b20]" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
              <circle cx="8.5" cy="8.5" r="4.75" />
              <path d="m12.25 12.25 4 4" stroke-linecap="round" />
            </svg>
            <input
              type="search"
              disabled
              placeholder="Pesquisar…"
              title="A busca será disponibilizada quando a API oferecer esse filtro."
              class="h-11 w-full cursor-not-allowed rounded-xl border border-[#e5d1c5] bg-white pr-4 pl-10 text-sm text-[#80695c] shadow-[0_8px_20px_-18px_rgba(60,30,15,.65)] outline-none placeholder:text-[#bd9d8c] disabled:opacity-85"
            />
          </label>
          <button
            type="button"
            disabled
            title="O filtro será disponibilizado quando a API oferecer esse recurso."
            class="flex h-11 shrink-0 cursor-not-allowed items-center justify-center gap-2 rounded-xl border border-[#e5d1c5] bg-[#fff6f1] px-4 text-sm font-medium text-[#8a6958] disabled:opacity-85"
          >
            <svg class="size-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M3 4.25h14l-5.5 6v4.25l-3 1.5v-5.75z" />
            </svg>
            Filtro
          </button>
            </div>
          </div>
        </div>

        <p v-if="mensagemDeErro" class="mt-8 rounded-xl border border-[#ecc9b7] bg-[#fff6f1] px-4 py-3 text-sm text-[#8a3f1c]" role="alert">
          {{ mensagemDeErro }}
        </p>

        <div v-else-if="carregando" class="mt-8 grid gap-5 md:grid-cols-2" aria-label="Carregando histórico">
          <div v-for="numero in 4" :key="numero" class="h-52 animate-pulse rounded-2xl border border-[#eadbd2] bg-white/70"></div>
        </div>

        <div v-else-if="jobsDaPagina.length === 0" class="mt-8 rounded-2xl border border-dashed border-[#ddc9bd] bg-white/65 px-6 py-14 text-center">
          <h2 class="font-serif text-2xl font-semibold">Nenhuma regra {{ tipoDoHistorico === 'arquivadas' ? 'arquivada' : 'salva' }} ainda</h2>
          <p class="mt-2 text-sm text-[#6b564a]">Quando houver uma regra nesta categoria, ela aparecerá aqui.</p>
        </div>

        <div v-else class="mt-8 grid gap-5 md:grid-cols-2">
          <article v-for="resumoDoJob in jobsDaPagina" :key="resumoDoJob.id" class="flex min-h-56 flex-col rounded-2xl border border-[#eadbd2] bg-white p-6 shadow-[0_16px_40px_-26px_rgba(60,30,15,0.5)]">
            <div class="flex items-start justify-between gap-4 border-b border-[#f0e2da] pb-4">
              <div>
                <h2 class="font-serif text-2xl font-semibold">Regra {{ resumoDoJob.id.slice(0, 8) }}</h2>
                <p class="mt-1 text-sm text-[#9c571e]">Criada em {{ new Date(resumoDoJob.criado_em).toLocaleDateString('pt-BR') }}</p>
              </div>
              <span class="rounded-full border border-[#edd0c0] bg-[#fff3ec] px-3 py-1 text-xs font-semibold text-[#8f470e]">{{ nomearStatus(resumoDoJob.status) }}</span>
            </div>

            <dl class="mt-5 grid gap-4 text-sm">
              <div class="flex items-start justify-between gap-4">
                <dt class="text-[#80695c]">Competência</dt>
                <dd class="text-right font-medium text-[#3a241a]">{{ formatarCompetencias(resumoDoJob.competencias) }}</dd>
              </div>
              <div class="flex items-center justify-between gap-4">
                <dt class="text-[#80695c]">Veredito</dt>
                <dd class="font-medium text-[#3a241a]">{{ nomearVeredito(resumoDoJob.veredito) }}</dd>
              </div>
            </dl>

            <a :href="`/jobs/${resumoDoJob.id}`" class="mt-auto pt-6 text-sm font-semibold text-[#b84e08] transition hover:text-[#843600]">
              Abrir relatório <span aria-hidden="true">→</span>
            </a>
          </article>
        </div>

        <nav v-if="!carregando && jobsDoHistorico.length > tamanhoDaPagina" class="mt-8 flex items-center justify-center gap-3" aria-label="Paginação do histórico">
          <button type="button" :disabled="paginaAtual === 0" class="rounded-lg border border-[#e3cfc3] bg-white px-4 py-2 text-sm font-medium text-[#6b564a] disabled:cursor-not-allowed disabled:opacity-45" @click="irParaPagina(paginaAtual - 1)">Anterior</button>
          <span class="text-sm text-[#6b564a]">Página {{ paginaAtual + 1 }} de {{ quantidadeDePaginas }}</span>
          <button type="button" :disabled="paginaAtual + 1 === quantidadeDePaginas" class="rounded-lg border border-[#e3cfc3] bg-white px-4 py-2 text-sm font-medium text-[#6b564a] disabled:cursor-not-allowed disabled:opacity-45" @click="irParaPagina(paginaAtual + 1)">Próxima</button>
        </nav>
      </section>
    </main>
  </div>
</template>
