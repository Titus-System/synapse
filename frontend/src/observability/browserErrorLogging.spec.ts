import { describe, expect, it, vi } from 'vitest'
import type { App } from 'vue'
import { instalarRegistroDeErrosDoNavegador } from './browserErrorLogging'

describe('instalarRegistroDeErrosDoNavegador', () => {
  it('registra um log estruturado para erro não tratado pelo Vue', () => {
    const aplicacao = { config: {} } as App
    const espiaoErro = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    instalarRegistroDeErrosDoNavegador(aplicacao)
    aplicacao.config.errorHandler?.(new TypeError('detalhe interno'), null, 'render')

    expect(espiaoErro).toHaveBeenCalledWith(
      expect.stringContaining('"service.name":"synapse-frontend"'),
    )
    expect(espiaoErro).toHaveBeenCalledWith(expect.stringContaining('"exception":"TypeError"'))

    espiaoErro.mockRestore()
  })
})
