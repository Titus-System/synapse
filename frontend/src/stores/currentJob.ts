import { ref } from 'vue'
import { defineStore } from 'pinia'
import { abrirAcompanhamentoJob } from '@/services/jobEvents'
import { apiClient } from '@/services/api'
import type { EventoEtapa, EventoEstado, EventoResultado, Job } from '@/types/api'

/**
 * Estado do job em acompanhamento, alimentado pelo stream SSE (via `abrirAcompanhamentoJob`,
 * src/services/jobEvents.ts) e por `GET /jobs/{id}` quando o stream pede reconciliação.
 *
 * Uso: qualquer componente obtém a instância chamando `usarStoreJobAtual()` — o Pinia garante que
 * toda chamada, em qualquer lugar da árvore, devolve a mesma instância singleton (enquanto a app
 * tiver um só `Pinia` registrado em main.ts). A view que exibe o progresso chama isso e, com a
 * instância em mãos, dispara `store.iniciarAcompanhamento(jobId)` ao montar (`onMounted`) e
 * `store.pararAcompanhamento()` ao desmontar (`onUnmounted`) — sair da tela sem parar deixa a
 * conexão SSE aberta indefinidamente. `iniciarAcompanhamento` fecha sozinho qualquer conexão
 * anterior antes de abrir a nova, então trocar de job só requer chamar de novo com o id novo, sem
 * parar manualmente primeiro.
 *
 * Nenhum evento "retorna" nada: os handlers internos apenas escrevem nos refs (`statusAtual`,
 * `etapaAtual`, `job`, `estadoConexao`, ...) conforme os eventos chegam, de forma idempotente e
 * sem calcular nada — tudo vem pronto da api. Qualquer componente que também tenha chamado
 * `usarStoreJobAtual()` lê esses refs (`store.statusAtual` etc.) e o Vue re-renderiza sozinho a
 * cada mudança, mesmo que esse componente nunca tenha chamado `iniciarAcompanhamento` — é a mesma
 * instância reativa por trás de toda chamada ao hook.
 */
export const usarStoreJobAtual = defineStore('current-job', () => {
  const idJob = ref<string | null>(null)
  const job = ref<Job | null>(null)
  const statusAtual = ref<string | null>(null)
  const statusAnterior = ref<string | null>(null)
  const motivoParada = ref<string | null>(null)
  const etapaAtual = ref<{ etapa: string; status: string } | null>(null)
  const estadoConexao = ref<'conectando' | 'aberta' | 'reconectando'>('conectando')

  let controladorConexao: ReturnType<typeof abrirAcompanhamentoJob> | null = null

  function iniciarAcompanhamento(jobId: string) {
    pararAcompanhamento()

    idJob.value = jobId
    job.value = null
    statusAtual.value = null
    statusAnterior.value = null
    motivoParada.value = null
    etapaAtual.value = null

    controladorConexao = abrirAcompanhamentoJob(jobId, {
      onEstado(evento: EventoEstado) {
        statusAnterior.value = evento.status_anterior ?? null
        statusAtual.value = evento.status
        motivoParada.value = evento.motivo ?? null
      },
      onEtapa(evento: EventoEtapa) {
        etapaAtual.value = { etapa: evento.etapa, status: evento.status }
      },
      onResultado(_evento: EventoResultado) {
        // Disparar fetch do job para capturar os números do resultado
        apiClient
          .consultarJob(jobId)
          .then((jobAtualizado) => {
            job.value = jobAtualizado
          })
          .catch(() => {
            // Erro ao consultar; o próximo evento estado do stream recupera
          })
      },
      onReconciliar(jobReconciliado: Job) {
        job.value = jobReconciliado
        statusAtual.value = jobReconciliado.status
      },
      onStatusConexao(status) {
        estadoConexao.value = status
      },
    })
  }

  function pararAcompanhamento() {
    if (controladorConexao) {
      controladorConexao.fechar()
      controladorConexao = null
    }
  }

  return {
    idJob,
    job,
    statusAtual,
    statusAnterior,
    motivoParada,
    etapaAtual,
    estadoConexao,
    iniciarAcompanhamento,
    pararAcompanhamento,
  }
})
