import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import type { Job } from '@/types/api'
import { usarStoreRegrasRecentes } from './regrasRecentes'
import { usarStoreRenomearRegra } from './renomearRegra'

vi.mock('@/services/api', () => ({
  apiClient: {
    listarJobs: vi.fn<typeof apiClient.listarJobs>(),
    renomearJob: vi.fn<typeof apiClient.renomearJob>(),
  },
}))

function respostaComNome(nome: string | null | undefined): Job {
  return { id: 'job-1', nome, regras: [] } as unknown as Job
}

async function prepararLista() {
  vi.mocked(apiClient.listarJobs).mockResolvedValue({
    itens: [
      {
        id: 'job-1',
        status: 'liberado',
        competencias: ['2025-09'],
        criado_em: '2026-09-19T12:00:00Z',
      },
    ],
    pagina: 0,
    tamanho: 100,
    total: 1,
  })
  const recentes = usarStoreRegrasRecentes()
  await recentes.carregar()
  return recentes
}

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
})

describe('usarStoreRenomearRegra', () => {
  it('envia o nome, aplica o nome da resposta e encerra a edição', async () => {
    const recentes = await prepararLista()
    vi.mocked(apiClient.renomearJob).mockResolvedValue(respostaComNome('Comissão de novembro'))
    const store = usarStoreRenomearRegra()

    store.iniciar('job-1', 'Regra · 19/09/2026')
    store.texto = '  Comissão de novembro  '
    const ok = await store.confirmar()

    expect(ok).toBe(true)
    expect(apiClient.renomearJob).toHaveBeenCalledWith('job-1', { nome: '  Comissão de novembro  ' })
    expect(recentes.regrasRecentes[0]?.rotulo).toBe('Comissão de novembro')
    expect(store.idEmEdicao).toBeNull()
  })

  it('mostra o nome devolvido pela API, e não o digitado', async () => {
    const recentes = await prepararLista()
    vi.mocked(apiClient.renomearJob).mockResolvedValue(respostaComNome('Nome aparado'))
    const store = usarStoreRenomearRegra()

    store.iniciar('job-1', 'Regra · 19/09/2026')
    store.texto = ' Nome aparado '
    await store.confirmar()

    expect(recentes.regrasRecentes[0]?.rotulo).toBe('Nome aparado')
  })

  it('mantém o nome e a edição aberta quando a API recusa', async () => {
    const recentes = await prepararLista()
    vi.mocked(apiClient.renomearJob).mockRejectedValue(
      new HttpError(403, 'Você não tem permissão para realizar esta ação.'),
    )
    const store = usarStoreRenomearRegra()

    store.iniciar('job-1', 'Regra · 19/09/2026')
    store.texto = 'Novo nome'
    const ok = await store.confirmar()

    expect(ok).toBe(false)
    expect(store.erro).toBe('Você não tem permissão para realizar esta ação.')
    expect(store.idEmEdicao).toBe('job-1')
    expect(store.enviando).toBe(false)
    expect(recentes.regrasRecentes[0]?.rotulo).toMatch(/^Regra · /)
  })

  it('cancelar não chama a API e mantém o nome', async () => {
    const recentes = await prepararLista()
    const store = usarStoreRenomearRegra()

    store.iniciar('job-1', 'Regra · 19/09/2026')
    store.texto = 'Outro'
    store.cancelar()

    expect(apiClient.renomearJob).not.toHaveBeenCalled()
    expect(store.idEmEdicao).toBeNull()
    expect(recentes.regrasRecentes[0]?.rotulo).toMatch(/^Regra · /)
  })

  it('bloqueia um segundo envio enquanto a requisição está em andamento', async () => {
    await prepararLista()
    let liberar!: (job: Job) => void
    vi.mocked(apiClient.renomearJob).mockReturnValue(
      new Promise<Job>((resolve) => {
        liberar = resolve
      }),
    )
    const store = usarStoreRenomearRegra()

    store.iniciar('job-1', 'Regra · 19/09/2026')
    store.texto = 'Novo'
    const primeiro = store.confirmar()
    const segundo = await store.confirmar()
    liberar(respostaComNome('Novo'))
    await primeiro

    expect(segundo).toBe(false)
    expect(apiClient.renomearJob).toHaveBeenCalledTimes(1)
  })

  it('não permite confirmar texto igual ao inicial, vazio ou acima de 100', () => {
    const store = usarStoreRenomearRegra()
    store.iniciar('job-1', 'Regra · 19/09/2026')

    expect(store.podeConfirmar).toBe(false)

    store.texto = '   '
    expect(store.mensagemDeValidacao).toBe('Informe um nome para a regra.')
    expect(store.podeConfirmar).toBe(false)

    store.texto = 'a'.repeat(101)
    expect(store.mensagemDeValidacao).toBe('O nome deve ter no máximo 100 caracteres.')
    expect(store.podeConfirmar).toBe(false)
  })

  it('conta por ponto de código: 100 emojis passam e 101 não', () => {
    const store = usarStoreRenomearRegra()
    store.iniciar('job-1', 'Regra · 19/09/2026')

    store.texto = '😀'.repeat(100)
    expect(store.tamanho).toBe(100)
    expect(store.podeConfirmar).toBe(true)

    store.texto = '😀'.repeat(101)
    expect(store.podeConfirmar).toBe(false)
  })
})