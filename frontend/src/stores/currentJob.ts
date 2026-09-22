import { ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'
import { abrirAcompanhamentoJob } from '@/services/jobEvents'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import type { EventoEtapa, Job, JobCriado, StatusJob } from '@/types/api'

export const usarStoreJobAtual = defineStore('current-job', () => {
  const idJob = ref<string | null>(null)
  const job = ref<Job | null>(null)
  const statusAtual = ref<StatusJob | null>(null)
  const statusAnterior = ref<StatusJob | null>(null)
  const motivoParada = ref<string | null>(null)
  const etapaAtual = ref<EventoEtapa | null>(null)
  const estadoConexao = ref<'conectando' | 'aberta' | 'reconectando'>('conectando')
  const carregando = ref(false)
  const erro = shallowRef<HttpError | null>(null)

  let conexao: ReturnType<typeof abrirAcompanhamentoJob> | null = null
  let acompanhamento = 0
  let consulta = 0

  function aplicarJob(atualizado: Job) {
    if (atualizado.id !== idJob.value) return
    consulta += 1
    job.value = atualizado
    statusAtual.value = atualizado.status
    motivoParada.value = atualizado.motivo ?? null
    carregando.value = false
    erro.value = null
  }

  function aplicarConfirmacao(confirmado: JobCriado) {
    if (confirmado.id !== idJob.value) return
    const regras = (job.value?.regras ?? []).filter((regra) => regra.id !== confirmado.regra.id)
    aplicarJob({ ...confirmado, regras: [...regras, confirmado.regra], simulacao: null })
  }

  async function consultarJob(): Promise<Job | null> {
    const id = idJob.value
    if (!id) return null
    const numero = ++consulta
    const ciclo = acompanhamento
    try {
      const atualizado = await apiClient.consultarJob(id)
      if (ciclo !== acompanhamento || numero !== consulta) return null
      aplicarJob(atualizado)
      return atualizado
    } catch (falha) {
      if (ciclo !== acompanhamento || numero !== consulta) return null
      erro.value =
        falha instanceof HttpError
          ? falha
          : new HttpError(0, 'Não foi possível consultar o processamento. Tente novamente.')
      if ([401, 403, 404].includes(erro.value.status)) {
        conexao?.fechar()
        conexao = null
      }
      return null
    } finally {
      if (ciclo === acompanhamento && numero === consulta) carregando.value = false
    }
  }

  async function iniciarAcompanhamento(id: string) {
    pararAcompanhamento()
    const ciclo = acompanhamento
    const ativo = () => ciclo === acompanhamento
    idJob.value = id
    job.value = null
    statusAtual.value = null
    statusAnterior.value = null
    motivoParada.value = null
    etapaAtual.value = null
    erro.value = null
    carregando.value = true
    estadoConexao.value = 'conectando'
    conexao = abrirAcompanhamentoJob(id, {
      onEstado(evento) {
        if (!ativo()) return
        statusAnterior.value = evento.status_anterior ?? null
        statusAtual.value = evento.status
        motivoParada.value = evento.motivo ?? null
        if (job.value)
          job.value = {
            ...job.value,
            status: evento.status,
            motivo: evento.motivo,
            simulacao: evento.status === job.value.status ? job.value.simulacao : null,
          }
        void consultarJob()
      },
      onEtapa(evento) {
        if (!ativo()) return
        etapaAtual.value = evento
        if (evento.status === 'concluido') void consultarJob()
      },
      onResultado() {
        if (ativo()) void consultarJob()
      },
      onReconciliar() {
        if (ativo()) void consultarJob()
      },
      onStatusConexao(status) {
        if (ativo()) estadoConexao.value = status
      },
    })
    await consultarJob()
  }

  function pararAcompanhamento() {
    acompanhamento += 1
    consulta += 1
    conexao?.fechar()
    conexao = null
  }

  return {
    idJob,
    job,
    statusAtual,
    statusAnterior,
    motivoParada,
    etapaAtual,
    estadoConexao,
    carregando,
    erro,
    iniciarAcompanhamento,
    pararAcompanhamento,
    consultarJob,
    aplicarJob,
    aplicarConfirmacao,
  }
})
