import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import roteador from './index'
import { usarStoreSessao } from '@/stores/session'

describe('roteador', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('resolve a raiz para a view de bootstrap', () => {
    expect(roteador.resolve('/').name).toBe('bootstrap')
  })

  it('inicia o login do Keycloak ao acessar uma rota de negócio sem sessão', async () => {
    const entrar = vi.spyOn(usarStoreSessao(), 'entrar').mockResolvedValue()

    await roteador.push('/nova-regra')

    expect(entrar).toHaveBeenCalledWith('/nova-regra')
  })

  it('permite uma rota de negócio para um usuário autenticado', async () => {
    usarStoreSessao().estaAutenticado = true

    await roteador.push('/nova-regra')

    expect(roteador.currentRoute.value.name).toBe('nova-regra')
  })
})
