import { describe, expect, it } from 'vitest'
import roteador from './index'

describe('roteador', () => {
  it('resolve a raiz para a view de bootstrap', () => {
    expect(roteador.resolve('/').name).toBe('bootstrap')
  })
})
