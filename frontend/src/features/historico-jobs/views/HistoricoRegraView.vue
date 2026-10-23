<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import type { Job, RegraVersionada } from '@/types/api'
import TheSidebar from '@/components/TheSidebar.vue'
import CartaoRegra from '@/components/CartaoRegra.vue'
import RelatorioSimulacao from '@/components/RelatorioSimulacao.vue'
import { useDetalhamento } from '@/composables/useDetalhamento'
import { consultarDetalhamento } from '@/services/detalhamento'
import { formatarReais } from '@/composables/apresentacaoDetalhamento'
import { simulacoesDoHistorico, versaoDeEncerramento } from '../composables/historicoDoJob'
import { usarStoreRegrasRecentes } from '@/stores/regrasRecentes'

const rota = useRoute()
const roteador = useRouter()
const regras = usarStoreRegrasRecentes()
const jobId = computed(() => String(rota.params.id))
const job = shallowRef<Job | null>(null)
const erro = ref('')
const carregando = ref(false)
const versaoId = ref('')
const simulacaoId = ref('')
let consulta: AbortController | undefined
const versoes = computed(() => [...(job.value?.regras ?? [])].sort((a, b) => b.versao - a.versao))
const encerramento = computed(() => (job.value ? versaoDeEncerramento(job.value) : undefined))
const regra = computed(() => versoes.value.find((item) => item.id === versaoId.value))
const simulacoes = computed(() => (job.value ? simulacoesDoHistorico(job.value) : []))
const execucoesDaVersao = computed(() =>
  simulacoes.value.filter((item) => item.regra_id === versaoId.value),
)
const simulacao = computed(() =>
  execucoesDaVersao.value.find((item) => item.id === simulacaoId.value),
)
const semVinculo = computed(() =>
  simulacoes.value.some((item) => !versoes.value.some((versao) => versao.id === item.regra_id)),
)
const identidade = computed(() => `${jobId.value}/${versaoId.value}/${simulacaoId.value}`)
const relatorio = useDetalhamento(identidade, (signal) =>
  consultarDetalhamento(jobId.value, simulacaoId.value, signal),
)
const { aberto, carregando: carregandoRelatorio, erro: erroRelatorio, resposta } = relatorio
function rotuloVersao(versao: RegraVersionada) {
  if (versao.id !== encerramento.value?.id) return 'Versão anterior / descartada'
  return job.value?.status === 'liberado'
    ? 'Versão final salva'
    : 'Versão de encerramento — arquivada'
}
const origens: Record<RegraVersionada['origem'], string> = {
  confirmacao_usuario: 'Formulário / confirmação',
  sugestao_adaptacao: 'Sugestão',
  reprocessamento: 'Reprocessamento',
  extracao: 'Proposta inicial',
  correcao: 'Correção',
}
watch(
  versaoId,
  () => {
    simulacaoId.value =
      execucoesDaVersao.value.find((item) => item.id === job.value?.simulacao?.id)?.id ??
      execucoesDaVersao.value[0]?.id ??
      ''
  },
  { flush: 'sync' },
)
async function carregar() {
  consulta?.abort()
  const controle = new AbortController()
  consulta = controle
  job.value = null
  versaoId.value = ''
  simulacaoId.value = ''
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
    versaoId.value = encerramento.value?.id ?? versoes.value[0]?.id ?? ''
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
onMounted(() => {
  void regras.carregar()
})
onBeforeUnmount(() => consulta?.abort())
</script>
<template>
  <div class="min-h-screen bg-[#fffaf7] text-[#2e1a10] lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]">
    <TheSidebar class="hidden h-screen lg:sticky lg:top-0 lg:flex" 
      :quantidade-arquivadas="regras.quantidadeArquivadas"
      :quantidade-salvas="regras.quantidadeSalvas"
      :regras-recentes="regras.regrasRecentes"
    />
    <main class="min-w-0 p-4 sm:p-8">
      <h1 class="mb-6 text-3xl font-bold">Histórico da regra</h1>
      <p v-if="carregando" role="status">Carregando histórico...</p>
      <div v-else-if="erro" role="alert">
        <p>{{ erro }}</p>
        <button class="mt-3 underline" @click="carregar">Tentar novamente</button>
      </div>
      <template v-else-if="job">
        <p class="mb-4">
          {{ job.status === 'liberado' ? 'Regra salva.' : 'Regra arquivada.' }} As versões
          anteriores mostram a evolução deste processamento.
        </p>
        <p v-if="!encerramento && job.status === 'liberado'" role="status" class="mb-4">
          Os dados disponíveis não identificam a versão final salva.
        </p>
        <p v-if="semVinculo" role="status" class="mb-4">
          Há resultado sem vínculo conhecido com uma versão da regra.
        </p>
        <p v-if="!versoes.length" role="status">Nenhuma versão disponível.</p>
        <label v-else class="mb-4 flex flex-col gap-2"
          >Versão da regra
          <select v-model="versaoId" class="rounded-lg border border-[#DFC0B2] bg-white p-3">
            <option v-for="versao in versoes" :key="versao.id" :value="versao.id">
              Versão {{ versao.versao }} · {{ rotuloVersao(versao) }} ·
              {{ origens[versao.origem] }} ·
              {{ new Date(versao.criada_em).toLocaleString('pt-BR') }}
            </option>
          </select>
        </label>
        <template v-if="regra">
          <h2 class="mb-3 font-bold">{{ rotuloVersao(regra) }}</h2>
          <CartaoRegra :regra="regra" :job="job" :carregando="false" :erro="false" />
          <p v-if="!execucoesDaVersao.length" role="status" class="my-5">
            Sem simulação disponível.
          </p>
          <label v-else class="my-5 flex flex-col gap-2"
            >Execução da simulação
            <select v-model="simulacaoId" class="rounded-lg border border-[#DFC0B2] bg-white p-3">
              <option v-for="execucao in execucoesDaVersao" :key="execucao.id" :value="execucao.id">
                {{ new Date(execucao.criado_em).toLocaleString('pt-BR') }} · {{ execucao.id
                }}{{ execucao.id === job.simulacao?.id ? ' · Resultado vigente' : '' }}
              </option>
            </select>
          </label>
          <section v-if="simulacao" class="my-5" aria-label="Resultado histórico">
            <p>
              {{
                simulacao.status === 'sucesso'
                  ? simulacao.veredito === 'viavel'
                    ? 'Resultado viável'
                    : simulacao.veredito === 'inviavel'
                      ? 'Resultado inviável'
                      : 'Resultado sem veredito'
                  : 'Execução sem resultado de sucesso'
              }}
            </p>
            <p>
              Meta de vendas:
              {{
                simulacao.meta_venda == null
                  ? 'Não registrada neste resultado'
                  : formatarReais(simulacao.meta_venda)
              }}
            </p>
            <p>
              Orçamento:
              {{
                simulacao.resultado?.totais?.orcamento == null
                  ? 'Não registrado neste resultado'
                  : formatarReais(simulacao.resultado.totais.orcamento)
              }}
            </p>
            <p v-if="simulacao.resultado?.totais">
              Comissão simulada: {{ formatarReais(simulacao.resultado.totais.simulado) }}
            </p>
          </section>
          <RelatorioSimulacao
            v-if="simulacao?.status === 'sucesso'"
            :aberto="aberto"
            :carregando="carregandoRelatorio"
            :erro="erroRelatorio"
            :linhas="resposta?.linhas"
            :regra="regra.representacao"
            :decomposicao="simulacao.resultado?.decomposicao"
            @alternar="relatorio.alternar"
            @tentar-novamente="relatorio.carregar"
          />
        </template>
      </template>
    </main>
  </div>
</template>
