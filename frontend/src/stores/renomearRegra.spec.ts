import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import type { Job } from '@/types/api'
import { usarStoreRenomearRegra } from './renomearRegra'

vi.mock('@/services/api', () => ({
  apiClient: {
    renomearJob: vi.fn<typeof apiClient.renomearJob>(),
  },
}))

function respostaComNome(nome: string | null | undefined): Job {
  return { id: 'job-1', nome, regras: [] } as unknown as Job
}

const rotuloPadrao = 'Regra · 19/09/2026'

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
})

describe('usarStoreRenomearRegra', () => {
  it('envia o nome, aplica o nome da resposta e encerra a edição', async () => {
    vi.mocked(apiClient.renomearJob).mockResolvedValue(respostaComNome('Comissão de novembro'))
    const store = usarStoreRenomearRegra()

    store.iniciar('job-1', 'Regra · 19/09/2026')
    store.texto = '  Comissão de novembro  '
    const ok = await store.confirmar()

    expect(ok).toBe(true)
    expect(apiClient.renomearJob).toHaveBeenCalledWith('job-1', { nome: '  Comissão de novembro  ' })
    expect(store.rotuloExibido('job-1', rotuloPadrao)).toBe('Comissão de novembro')
    expect(store.idEmEdicao).toBeNull()
  })

  it('mostra o nome devolvido pela API, e não o digitado', async () => {
    vi.mocked(apiClient.renomearJob).mockResolvedValue(respostaComNome('Nome aparado'))
    const store = usarStoreRenomearRegra()

    store.iniciar('job-1', 'Regra · 19/09/2026')
    store.texto = ' Nome aparado '
    await store.confirmar()

    expect(store.rotuloExibido('job-1', rotuloPadrao)).toBe('Nome aparado')
  })

  it('mantém o nome e a edição aberta quando a API recusa', async () => {
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
    expect(store.rotuloExibido('job-1', rotuloPadrao)).toBe(rotuloPadrao)
  })

  it('mostra a mensagem do código quando a API recusa a validação do nome', async () => {
    vi.mocked(apiClient.renomearJob).mockRejectedValue(
      new HttpError(400, 'Revise os dados informados e tente novamente.', {
        code: 'requisicao_invalida',
      }),
    )
    const store = usarStoreRenomearRegra()

    store.iniciar('job-1', 'Regra · 19/09/2026')
    store.texto = 'Novo nome'
    await store.confirmar()

    expect(store.erro).toBe(
      'Não foi possível enviar os dados. Revise as informações e tente novamente.',
    )
  })

  it('cancelar não chama a API e mantém o nome', async () => {
    const store = usarStoreRenomearRegra()

    store.iniciar('job-1', 'Regra · 19/09/2026')
    store.texto = 'Outro'
    store.cancelar()

    expect(apiClient.renomearJob).not.toHaveBeenCalled()
    expect(store.idEmEdicao).toBeNull()
    expect(store.rotuloExibido('job-1', rotuloPadrao)).toBe(rotuloPadrao)
  })

  it('bloqueia um segundo envio enquanto a requisição está em andamento', async () => {
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