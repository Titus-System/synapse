<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import type { Job, JobResumo, RegraVersionada } from '@/types/api'
import TheSidebar from '@/components/TheSidebar.vue'
import TheProcessHeader from '@/components/TheProcessHeader.vue'
import RelatorioSimulacao from '@/components/RelatorioSimulacao.vue'
import { useDetalhamento } from '@/composables/useDetalhamento'
import { observarConsulta } from '@/observability/consultasLogging'
import { consultarDetalhamento } from '@/services/detalhamento'
import { listarTodosOsJobs } from '../services/historicoJobs.api'
import ResumoRegraHistorica from '../components/ResumoRegraHistorica.vue'
import ResultadoVersaoHistorica from '../components/ResultadoVersaoHistorica.vue'
import { simulacaoAnterior, simulacoesDoHistorico, versaoDeEncerramento } from '../composables/historicoDoJob'

const rota = useRoute()
const roteador = useRouter()
const jobId = computed(() => String(rota.params.id))
const job = shallowRef<Job | null>(null)
const resumosDosJobs = shallowRef<JobResumo[]>([])
const erro = ref('')
const carregando = ref(false)
const mostrarSimulacoes = ref(false)
const versaoId = ref('')
const simulacaoId = ref('')
const selecoes = ref<Record<string, string>>({})
let consulta: AbortController | undefined
const versoes = computed(() => [...(job.value?.regras ?? [])].sort((a, b) => b.versao - a.versao))
const jobsArquivados = computed(() => resumosDosJobs.value.filter((item) => item.status === 'arquivado'))
const jobsSalvos = computed(() => resumosDosJobs.value.filter((item) => item.status !== 'arquivado'))
const regrasRecentes = computed(() =>
  resumosDosJobs.value.slice(0, 6).map((item) => ({
    identificador: item.id,
    rotulo: `Regra · ${new Date(item.criado_em).toLocaleDateString('pt-BR')}`,
  })),
)
const encerramento = computed(() => (job.value ? versaoDeEncerramento(job.value) : undefined))
const ordenadas = computed(() => [
  ...(encerramento.value ? [encerramento.value] : []),
  ...versoes.value.filter((item) => item.id !== encerramento.value?.id),
])
const regra = computed(() => versoes.value.find((item) => item.id === versaoId.value))
const simulacoes = computed(() => (job.value ? simulacoesDoHistorico(job.value) : []))
const execucoes = (id: string) => simulacoes.value.filter((item) => item.regra_id === id)
const execucaoDaVersao = (id: string) => {
  const opcoes = execucoes(id)
  return (
    opcoes.find((item) => item.id === selecoes.value[id]) ??
    opcoes.find((item) => item.id === job.value?.simulacao?.id) ??
    opcoes[0]
  )
}
const simulacao = computed(() =>
  execucoes(versaoId.value).find((item) => item.id === simulacaoId.value),
)
const semVinculo = computed(() =>
  simulacoes.value.some((item) => !versoes.value.some((versao) => versao.id === item.regra_id)),
)
const identidade = computed(() => `${jobId.value}/${versaoId.value}/${simulacaoId.value}`)
const relatorio = useDetalhamento(identidade, (signal) =>
  consultarDetalhamento(jobId.value, simulacaoId.value, signal),
)
const { aberto, carregando: carregandoRelatorio, erro: erroRelatorio, resposta } = relatorio
function tituloVersao(versao: RegraVersionada) {
  if (!encerramento.value) return 'Versão registrada'
  if (versao.id !== encerramento.value?.id) return 'Regra Descartada'
  return job.value?.status === 'liberado' ? 'Regra Final' : 'Versão de encerramento'
}
function tituloDoResumo(versao: RegraVersionada) {
  if (encerramento.value?.id === versao.id && job.value?.status === 'liberado') return 'Regra Final'
  return `Versão ${versao.versao}`
}
function selecionar(versao: RegraVersionada, id?: string) {
  if (id) selecoes.value[versao.id] = id
  versaoId.value = versao.id
  simulacaoId.value = execucaoDaVersao(versao.id)?.id ?? ''
}
async function carregar() {
  consulta?.abort()
  const controle = new AbortController()
  consulta = controle
  job.value = null
  resumosDosJobs.value = []
  versaoId.value = ''
  simulacaoId.value = ''
  selecoes.value = {}
  mostrarSimulacoes.value = false
  erro.value = ''
  carregando.value = true
  try {
    const recebido = await apiClient.consultarJob(jobId.value, controle.signal)
    if (consulta !== controle || controle.signal.aborted) return
    if (!['liberado', 'arquivado'].includes(recebido.status)) {
      await roteador.replace(
        `/jobs/${encodeURIComponent(recebido.id)}${recebido.status === 'aguardando_confirmacao_parametros' ? '/correcao' : ''}`,
      )
      return
    }
    job.value = recebido
    try {
      resumosDosJobs.value = await observarConsulta(
        'listar_jobs',
        jobId.value,
        () => listarTodosOsJobs(controle.signal),
        controle.signal,
      )
    } catch {
      if (controle.signal.aborted || consulta !== controle) return
    }
    const inicial = encerramento.value ?? versoes.value[0]
    if (inicial) selecionar(inicial)
  } catch (falha) {
    if (consulta !== controle || controle.signal.aborted) return
    erro.value =
      falha instanceof HttpError
        ? falha.message
        : 'Não foi possível carregar o histórico. Tente novamente.'
  } finally {
    if (consulta === controle) carregando.value = false
  }
}
watch(
  jobId,
  () => {
    void carregar()
  },
  { immediate: true },
)
onBeforeUnmount(() => consulta?.abort())
</script>

<template>
  <div class="min-h-[100dvh] bg-[#fdf7f3] text-[#2e1a10] lg:grid lg:h-[100dvh] lg:grid-cols-[16rem_minmax(0,1fr)] lg:overflow-hidden">
    <TheSidebar
      class="hidden lg:flex"
      :secao-ativa="job?.status === 'arquivado' ? 'arquivadas' : 'salvas'"
      :quantidade-arquivadas="jobsArquivados.length"
      :quantidade-salvas="jobsSalvos.length"
      :regras-recentes="regrasRecentes"
    />
    <main class="min-w-0 bg-[radial-gradient(circle_at_top,#fffdfb_0%,#fdf7f3_48%,#f8eee8_100%)] lg:min-h-0 lg:overflow-y-auto">
      <TheProcessHeader :etapa-da-rota="null" historico />
      <div class="mx-auto max-w-4xl px-4 py-10 sm:px-8 sm:pt-20 sm:pb-16">
        <p v-if="carregando" role="status">Carregando histórico...</p>
        <div v-else-if="erro" role="alert">
          <p>{{ erro }}</p>
          <button class="mt-3 underline" @click="carregar">Tentar novamente</button>
        </div>
        <template v-else-if="job">
          <p class="sr-only">
            {{ job.status === 'liberado' ? 'Regra salva.' : 'Regra arquivada.' }}
          </p>
          <p v-if="!encerramento && job.status === 'liberado'" role="status" class="mb-5">
            Os dados disponíveis não identificam a versão final salva.
          </p>
          <p v-if="semVinculo" role="status" class="mb-5">
            Há resultado sem vínculo conhecido com uma versão da regra.
          </p>
          <p v-if="!versoes.length" role="status">Nenhuma versão disponível.</p>
          <template v-if="regra">
            <ResumoRegraHistorica
              :regra="regra"
              :simulacao="simulacao"
              :titulo="tituloDoResumo(regra)"
            >
              <RelatorioSimulacao
                v-if="simulacao?.status === 'sucesso'"
                sem-margens
                :aberto="aberto"
                :carregando="carregandoRelatorio"
                :erro="erroRelatorio"
                :linhas="resposta?.linhas"
                :regra="regra.representacao"
                :decomposicao="simulacao.resultado?.decomposicao"
                @alternar="relatorio.alternar"
                @tentar-novamente="relatorio.carregar"
              />
              <p v-else role="status" class="mb-6 text-sm text-[#80695c]">
                Sem simulação disponível.
              </p>
            </ResumoRegraHistorica>
            <div class="my-8 flex justify-center">
              <button
                type="button"
                class="flex min-h-11 cursor-pointer items-center gap-2 text-sm font-semibold text-[#9D4400] hover:underline focus-visible:outline-2 focus-visible:outline-offset-4"
                :aria-expanded="mostrarSimulacoes"
                aria-controls="simulacoes-do-historico"
                @click="mostrarSimulacoes = !mostrarSimulacoes"
              >
                Ver simulação <span aria-hidden="true">{{ mostrarSimulacoes ? '⌃' : '⌄' }}</span>
              </button>
            </div>
            <div v-if="mostrarSimulacoes" id="simulacoes-do-historico" class="space-y-14 pb-8">
              <template v-for="versao in ordenadas" :key="versao.id">
              <ResultadoVersaoHistorica
                :regra="versao"
                :titulo="tituloVersao(versao)"
                :simulacao="execucaoDaVersao(versao.id)"
                :execucoes="execucoes(versao.id)"
                :vigente-id="job.simulacao?.id"
                @selecionar-execucao="selecionar(versao, $event)"
              />
              <ResultadoVersaoHistorica
                v-if="execucaoDaVersao(versao.id)?.anterior_a_meta_sugerida"
                :regra="versao"
                titulo="Regra Descartada"
                :simulacao="simulacaoAnterior(execucaoDaVersao(versao.id))"
                :execucoes="[]"
                anterior
              />
              <p
                v-else-if="execucaoDaVersao(versao.id)?.meta_sugerida_aceita_em"
                role="status"
                class="text-sm text-[#80695c]"
              >O resultado anterior ao aceite não pôde ser recuperado com segurança neste histórico.</p>
              </template>
            </div>
          </template>
        </template>
      </div>
    </main>
  </div>
</template>
