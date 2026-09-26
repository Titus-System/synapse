import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { usarStoreJobAtual } from './currentJob'
import { usarStoreSessao } from './session'

describe('stores globais', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('inicia sem sessão autenticada', () => {
    expect(usarStoreSessao().estaAutenticado).toBe(false)
  })

  it('inicia sem job atual', () => {
    expect(usarStoreJobAtual().idJob).toBeNull()
  })
})
