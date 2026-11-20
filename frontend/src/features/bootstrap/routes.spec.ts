import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import roteador from '@/router'
import { usarStoreSessao } from '@/stores/session'
beforeEach(() => setActivePinia(createPinia()))
it('sem sessão, inicia o login com retorno à raiz', async () => {
  const entrar = vi.spyOn(usarStoreSessao(), 'entrar').mockResolvedValue()
  await roteador.push('/')
  expect(entrar).toHaveBeenCalledWith('/')
})
it.each([
  ['auditor', '/auditoria'],
  ['profissional-rh', '/nova-regra'],
  [undefined, '/nova-regra'],
] as const)('direciona %s autenticado para %s', async (papel, destino) => {
  const sessao = usarStoreSessao()
  sessao.estaAutenticado = true
  sessao.papel = papel
  await roteador.push('/')
  expect(roteador.currentRoute.value.path).toBe(destino)
})
