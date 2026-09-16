import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usarStoreJobAtual } from './currentJob'
import * as jobEventsModule from '@/services/jobEvents'

vi.mock('@/services/jobEvents')

describe('usarStoreJobAtual', () => {
  let mockFechador: { fechar: () => void }

  beforeEach(() => {
    setActivePinia(createPinia())
    mockFechador = { fechar: vi.fn<() => void>() }
    vi.mocked(jobEventsModule.abrirAcompanhamentoJob).mockReturnValue(mockFechador)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('inicializa com estado vazio', () => {
    const store = usarStoreJobAtual()

    expect(store.idJob).toBeNull()
    expect(store.job).toBeNull()
    expect(store.statusAtual).toBeNull()
  })

  it('iniciarAcompanhamento abre conexão SSE e armazena id', () => {
    const store = usarStoreJobAtual()

    store.iniciarAcompanhamento('job-123')

    expect(jobEventsModule.abrirAcompanhamentoJob).toHaveBeenCalledWith('job-123', expect.any(Object))
    expect(store.idJob).toBe('job-123')
  })

  it('pararAcompanhamento fecha a conexão', () => {
    const store = usarStoreJobAtual()
    store.iniciarAcompanhamento('job-123')

    store.pararAcompanhamento()

    expect(mockFechador.fechar).toHaveBeenCalled()
  })

  it('iniciarAcompanhamento fecha a conexão anterior antes de abrir uma nova', () => {
    const store = usarStoreJobAtual()
    store.iniciarAcompanhamento('job-123')
    const primeiraFechada = mockFechador.fechar

    store.iniciarAcompanhamento('job-456')

    expect(primeiraFechada).toHaveBeenCalled()
    expect(store.idJob).toBe('job-456')
  })
})
