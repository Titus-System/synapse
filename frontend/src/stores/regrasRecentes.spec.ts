import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { apiClient } from '@/services/api'
import type { JobResumo, PaginaJobs } from '@/types/api'
import { usarStoreRegrasRecentes } from './regrasRecentes'

vi.mock('@/services/api', () => ({
  apiClient: { listarJobs: vi.fn<typeof apiClient.listarJobs>() },
}))

function resumo(numero: number, extra: Partial<JobResumo> = {}): JobResumo {
  return {
    id: `job-${numero}`,
    status: 'liberado',
    competencias: ['2025-09'],
    criado_em: '2026-09-19T12:00:00Z',
    ...extra,
  }
}

function pagina(itens: JobResumo[], total = itens.length): PaginaJobs {
  return { itens, pagina: 0, tamanho: 100, total }
}

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
})

describe('usarStoreRegrasRecentes', () => {
  it('carrega todas as páginas e expõe as seis mais recentes com contagens', async () => {
    const primeira = Array.from({ length: 100 }, (_, i) => resumo(i + 1))
    const segunda = [resumo(101, { status: 'arquivado' })]
    vi.mocked(apiClient.listarJobs)
      .mockResolvedValueOnce(pagina(primeira, 101))
      .mockResolvedValueOnce(pagina(segunda, 101))

    const store = usarStoreRegrasRecentes()
    await store.carregar()

    expect(store.resumos).toHaveLength(101)
    expect(store.regrasRecentes).toHaveLength(6)
    expect(store.quantidadeArquivadas).toBe(1)
    expect(store.quantidadeSalvas).toBe(100)
  })

  it('usa o nome quando existe e o rótulo com a data quando não existe', async () => {
    vi.mocked(apiClient.listarJobs).mockResolvedValue(
      pagina([resumo(1, { nome: 'Comissão de novembro' }), resumo(2)]),
    )

    const store = usarStoreRegrasRecentes()
    await store.carregar()

    expect(store.regrasRecentes[0]?.rotulo).toBe('Comissão de novembro')
    expect(store.regrasRecentes[1]?.rotulo).toMatch(/^Regra · \d{2}\/\d{2}\/\d{4}$/)
  })

  it('aplica o nome recebido da API só no job indicado', async () => {
    vi.mocked(apiClient.listarJobs).mockResolvedValue(pagina([resumo(1), resumo(2)]))
    const store = usarStoreRegrasRecentes()
    await store.carregar()

    store.aplicarNome('job-2', 'Novo nome')

    expect(store.regrasRecentes[1]?.rotulo).toBe('Novo nome')
    expect(store.regrasRecentes[0]?.rotulo).toMatch(/^Regra · /)
  })

  it('zera a lista e marca erro quando a consulta falha', async () => {
    vi.mocked(apiClient.listarJobs).mockRejectedValue(new Error('falha'))
    const store = usarStoreRegrasRecentes()

    await store.carregar()

    expect(store.resumos).toEqual([])
    expect(store.erro).toBe(true)
    expect(store.carregando).toBe(false)
  })

  it('ignora a resposta de uma chamada antiga quando há uma mais nova', async () => {
    let liberar!: (valor: PaginaJobs) => void
    vi.mocked(apiClient.listarJobs)
      .mockReturnValueOnce(new Promise<PaginaJobs>((resolve) => { liberar = resolve }))
      .mockResolvedValueOnce(pagina([resumo(2)]))
    const store = usarStoreRegrasRecentes()

    const antiga = store.carregar()
    await store.carregar()
    liberar(pagina([resumo(1)]))
    await antiga

    expect(store.resumos.map((item) => item.id)).toEqual(['job-2'])
  })
})