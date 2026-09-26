import { describe, it, expect, beforeEach, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { usarStoreJobAtual } from './currentJob'
import { abrirAcompanhamentoJob } from '@/services/jobEvents'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { jobFixture, jobCriadoFixture, respostaPendente } from '@/services/job.fixtures'
import type { Job } from '@/types/api'

vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: vi.fn<typeof abrirAcompanhamentoJob>(),
}))
vi.mock('@/services/api', () => ({
  apiClient: { consultarJob: vi.fn<typeof apiClient.consultarJob>() },
}))

function handlers(indice = 0) {
  return vi.mocked(abrirAcompanhamentoJob).mock.calls[indice]![1]
}

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture())
  vi.mocked(abrirAcompanhamentoJob).mockImplementation(() => ({ fechar: vi.fn<() => void>() }))
})

describe('usarStoreJobAtual', () => {
  it('busca a fotografia inicial e abre o stream', async () => {
    const store = usarStoreJobAtual()
    await store.iniciarAcompanhamento('job-1')
    expect(store.job).toEqual(jobFixture())
    expect(store.carregando).toBe(false)
    expect(abrirAcompanhamentoJob).toHaveBeenCalledWith('job-1', expect.any(Object))
  })

  it('reconsulta os dados em mudanças de estado, resultado e reconexão', async () => {
    const store = usarStoreJobAtual()
    await store.iniciarAcompanhamento('job-1')
    const atualizado = jobFixture({ status: 'simulando' })
    vi.mocked(apiClient.consultarJob).mockResolvedValue(atualizado)
    handlers().onEstado({ job_id: 'job-1', status: 'simulando' })
    expect(store.job?.status).toBe('simulando')
    await flushPromises()
    handlers().onResultado({ job_id: 'job-1', simulacao_id: 'simulacao-1', status: 'sucesso' })
    await flushPromises()
    handlers().onReconciliar()
    await flushPromises()
    expect(apiClient.consultarJob).toHaveBeenCalledTimes(4)
  })

  it('ignora uma consulta e eventos que chegam depois da troca de job', async () => {
    const antiga = respostaPendente<Job>()
    vi.mocked(apiClient.consultarJob).mockReturnValueOnce(antiga.promise)
    const store = usarStoreJobAtual()
    const primeira = store.iniciarAcompanhamento('job-1')
    const fechar = vi.mocked(abrirAcompanhamentoJob).mock.results[0]!.value.fechar
    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture({ id: 'job-2' }))
    await store.iniciarAcompanhamento('job-2')
    handlers(0).onEstado({ job_id: 'job-1', status: 'erro' })
    antiga.resolve(jobFixture())
    await primeira
    expect(store.job?.id).toBe('job-2')
    expect(store.job?.status).toBe('aguardando_decisao_usuario')
    expect(fechar).toHaveBeenCalledOnce()
  })

  it('mantém o motivo da parada que a reconsulta do mesmo status não devolve', async () => {
    const store = usarStoreJobAtual()
    await store.iniciarAcompanhamento('job-1')
    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture({ status: 'erro' }))

    handlers().onEstado({
      job_id: 'job-1',
      status: 'erro',
      motivo: 'A regra usa um elemento sem implementação correspondente.',
    })
    await flushPromises()

    expect(store.statusAtual).toBe('erro')
    expect(store.motivoParada).toBe('A regra usa um elemento sem implementação correspondente.')

    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture({ status: 'simulando' }))
    handlers().onEstado({ job_id: 'job-1', status: 'simulando' })
    await flushPromises()

    expect(store.motivoParada).toBeNull()
  })

  it('não sobrescreve um resultado novo com uma resposta antiga do mesmo job', async () => {
    const antiga = respostaPendente<Job>()
    vi.mocked(apiClient.consultarJob).mockReturnValueOnce(antiga.promise)
    const store = usarStoreJobAtual()
    const inicio = store.iniciarAcompanhamento('job-1')
    handlers().onResultado({ job_id: 'job-1', simulacao_id: 'simulacao-1', status: 'sucesso' })
    await flushPromises()
    antiga.resolve(jobFixture({ status: 'simulando', simulacao: null }))
    await inicio
    expect(store.job?.status).toBe('aguardando_decisao_usuario')
    expect(store.job?.simulacao?.id).toBe('simulacao-1')
  })

  it('invalida consultas pendentes ao confirmar outra simulação', async () => {
    const store = usarStoreJobAtual()
    await store.iniciarAcompanhamento('job-1')
    const antiga = respostaPendente<Job>()
    vi.mocked(apiClient.consultarJob).mockReturnValueOnce(antiga.promise)
    const consulta = store.consultarJob()
    store.aplicarConfirmacao(jobCriadoFixture({ status: 'gerando_regra' }))
    antiga.resolve(jobFixture())
    await consulta
    expect(store.job?.status).toBe('gerando_regra')
    expect(store.job?.simulacao).toBeNull()
  })

  it('fecha o stream ao sair e ignora a resposta pendente', async () => {
    const pendente = respostaPendente<Job>()
    vi.mocked(apiClient.consultarJob).mockReturnValueOnce(pendente.promise)
    const store = usarStoreJobAtual()
    const inicio = store.iniciarAcompanhamento('job-1')
    store.pararAcompanhamento()
    pendente.resolve(jobFixture())
    await inicio
    expect(store.job).toBeNull()
    expect(vi.mocked(abrirAcompanhamentoJob).mock.results[0]!.value.fechar).toHaveBeenCalledOnce()
  })

  it('expõe o erro de consulta e encerra o stream de um job inexistente', async () => {
    vi.mocked(apiClient.consultarJob).mockRejectedValue(new HttpError(404, 'Job não encontrado.'))
    const store = usarStoreJobAtual()
    await store.iniciarAcompanhamento('job-1')
    expect(store.erro?.status).toBe(404)
    expect(store.carregando).toBe(false)
    expect(vi.mocked(abrirAcompanhamentoJob).mock.results[0]!.value.fechar).toHaveBeenCalledOnce()
  })
})
