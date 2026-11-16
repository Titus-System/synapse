import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import * as keycloak from '@/services/keycloak'
import { usarStoreSessao } from './session'
vi.mock('@/services/keycloak', () => ({
  inicializarKeycloak: vi.fn<() => Promise<boolean>>(),
  obterPapelDeNegocio: vi.fn<() => 'auditor' | 'profissional-rh' | undefined>(),
  obterLoginDoUsuario: vi.fn<() => string | undefined>(),
  iniciarLogin: vi.fn<() => Promise<void>>(),
  iniciarLogout: vi.fn<() => Promise<void>>(),
  limparTokenDoKeycloak: vi.fn<() => void>(),
}))
beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  vi.mocked(keycloak.inicializarKeycloak).mockResolvedValue(true)
  vi.mocked(keycloak.obterPapelDeNegocio).mockReturnValue('auditor')
  vi.mocked(keycloak.obterLoginDoUsuario).mockReturnValue('auditor.teste')
})
it('guarda papel e login após inicializar', async () => {
  const sessao = usarStoreSessao()
  await sessao.inicializar()
  expect(sessao.papel).toBe('auditor')
  expect(sessao.login).toBe('auditor.teste')
})
it.each(['sair', 'encerrarPorSessaoInvalida'] as const)('limpa dados ao %s', async (acao) => {
  const sessao = usarStoreSessao()
  await sessao.inicializar()
  await sessao[acao]()
  expect(sessao.papel).toBeUndefined()
  expect(sessao.login).toBeUndefined()
  expect(sessao.estaAutenticado).toBe(false)
})
it('limpa papel quando uma inicialização falha', async () => {
  const sessao = usarStoreSessao()
  await sessao.inicializar()
  vi.mocked(keycloak.inicializarKeycloak).mockRejectedValue(new Error('falha'))
  await sessao.inicializar()
  expect(sessao.papel).toBeUndefined()
  expect(sessao.indisponivel).toBe(true)
})
it('não lê papel de sessão não autenticada', async () => {
  vi.mocked(keycloak.inicializarKeycloak).mockResolvedValue(false)
  await usarStoreSessao().inicializar()
  expect(keycloak.obterPapelDeNegocio).not.toHaveBeenCalled()
})
