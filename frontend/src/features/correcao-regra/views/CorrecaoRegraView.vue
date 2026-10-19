<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed, watch } from 'vue'
import { apiClient } from '@/services/api'
import type { JobResumo } from '@/types/api'
import { useRoute, useRouter } from 'vue-router'
import { useCorrecao } from '../composables/useCorrecao'
import ConversaRodadas from '../components/ConversaRodadas.vue'
import EntradaCorrecao from '../components/EntradaCorrecao.vue'
import TheProcessHeader from '@/components/TheProcessHeader.vue'
import TheSidebar from '@/components/TheSidebar.vue'

const rota = useRoute()
const router = useRouter()
const jobId = computed(() => (typeof rota.params.id === 'string' ? rota.params.id : ''))
const {
  rodadas,
  texto,
  carregando,
  enviando,
  erroLeitura,
  erroEnvio,
  habilitada,
  podeEnviar,
  encerrado,
  semCorrecao,
  seguirProcessamento,
  atualizar,
  enviar,
} = useCorrecao(jobId)
watch(seguirProcessamento, (seguir) => {
  if (seguir) void router.replace(`/jobs/${encodeURIComponent(jobId.value)}`)
})

const regrasRecentes = ref<{ identificador: string; rotulo: string }[]>([])
const quantidadeArquivadas = ref(0)
const quantidadeSalvas = ref(0)
const carregandoHistorico = ref(true)
const erroHistorico = ref(false)
const controlador = new AbortController()

async function carregarHistorico() {
  if (controlador.signal.aborted) return
  carregandoHistorico.value = true
  erroHistorico.value = false
  const inicio = performance.now()
  let resultado = 'sucesso'
  try {
    const jobs: JobResumo[] = []
    let pagina = 0
    let total = 0
    do {
      const resposta = await apiClient.listarJobs({ pagina, tamanho: 100 }, controlador.signal)
      if (controlador.signal.aborted) return
      jobs.push(...resposta.itens)
      total = resposta.total
      pagina += 1
      if (!resposta.itens.length) break
    } while (jobs.length < total)
    regrasRecentes.value = jobs.slice(0, 6).map((job) => ({
      identificador: job.id,
      rotulo: `Regra · ${new Date(job.criado_em).toLocaleDateString('pt-BR')}`,
    }))
    quantidadeArquivadas.value = jobs.filter((job) => job.status === 'arquivado').length
    quantidadeSalvas.value = jobs.length - quantidadeArquivadas.value
  } catch {
    if (controlador.signal.aborted) return
    resultado = 'falha'
    erroHistorico.value = true
  } finally {
    if (!controlador.signal.aborted) {
      carregandoHistorico.value = false
      const registro = JSON.stringify({
        timestamp: new Date().toISOString(),
        level: resultado === 'sucesso' ? 'INFO' : 'ERROR',
        message: 'Consulta do resumo de regras concluída',
        'service.name': 'synapse-frontend',
        extra: { operacao: 'listar_regras', resultado, duracao_ms: performance.now() - inicio },
      })
      if (resultado === 'sucesso') console.info(registro)
      else console.error(registro)
    }
  }
}
onMounted(carregarHistorico)
onBeforeUnmount(() => controlador.abort())
</script>

<template>
  <div
    class="h-[100dvh] overflow-hidden bg-[#fffaf7] font-sans text-[#584237] lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]"
  >
    <TheSidebar
      v-if="!carregandoHistorico && !erroHistorico"
      class="sticky top-0 hidden h-screen lg:flex"
      :regras-recentes="regrasRecentes"
      :quantidade-salvas="quantidadeSalvas"
      :quantidade-arquivadas="quantidadeArquivadas"
    />
    <aside
      v-else
      class="sticky top-0 hidden h-screen flex-col bg-[#3b2318] p-5 text-[#f6eae3] lg:flex"
    >
      <span class="font-serif text-xl font-bold">Synapse</span>
      <RouterLink
        to="/nova-regra"
        class="mt-6 rounded-lg bg-[#f26b0f] px-4 py-3 text-center text-sm"
        >Nova Regra</RouterLink
      >
      <p v-if="carregandoHistorico" role="status" class="mt-5 text-sm">Carregando histórico...</p>
      <div v-else role="alert" class="mt-5 text-sm">
        <p>Não foi possível carregar o histórico.</p>
        <button type="button" class="mt-3 underline" @click="carregarHistorico">
          Tentar novamente
        </button>
      </div>
    </aside>
    <main class="flex h-full min-h-0 min-w-0 flex-col">
      <TheProcessHeader etapa-da-rota="conversa" class="sticky top-0 z-10 shrink-0" />
      <div class="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 pb-7 sm:px-8 lg:px-10">
        <section class="mx-auto mt-10 max-w-2xl text-center sm:mt-16">
          <h1 class="font-serif text-3xl text-[#321f16]">Refine sua Regra</h1>
          <p class="mt-4 text-base leading-relaxed text-[#7b6559]">
            Nossa IA começou a estruturar sua regra. Responda às perguntas abaixo para detalhar as
            condições e ações específicas.
          </p>
        </section>
        <section
          class="mx-auto mt-5 w-full max-w-6xl flex-1 space-y-7 pb-8"
          aria-label="Conversa sobre a regra"
          aria-live="polite"
        >
          <p v-if="!jobId" role="status">Abra uma regra para corrigir.</p>
          <p v-else-if="carregando" role="status">Carregando conversa...</p>
          <div v-if="erroLeitura" role="alert">
            {{ erroLeitura }}
            <button type="button" class="underline" @click="atualizar">
              Tentar atualizar conversa
            </button>
          </div>
          <ConversaRodadas :rodadas="rodadas" />
          <p v-if="encerrado" role="status">Esta conversa está disponível apenas para consulta.</p>
          <p v-if="semCorrecao" role="status">Esta regra não tem pontos para corrigir.</p>
        </section>
      </div>
      <footer class="mx-auto w-full max-w-3xl shrink-0 bg-[#fffaf7] px-4 py-4 sm:px-8">
        <EntradaCorrecao
          v-if="!encerrado && !semCorrecao"
          :key="jobId"
          v-model:texto="texto"
          :job-id="jobId"
          :habilitada="habilitada"
          :pode-enviar="podeEnviar"
          :enviando="enviando"
          @enviar="enviar()"
          @enviar-voz="enviar"
        />
        <p v-if="enviando" role="status">Enviando correção...</p>
        <p v-if="erroEnvio" role="alert">{{ erroEnvio }}</p>
        <p class="mt-4 text-center text-xs text-[#a38a7e]">
          A IA pode cometer erros. Verifique a regra estruturada.
        </p>
      </footer>
    </main>
  </div>
</template>
