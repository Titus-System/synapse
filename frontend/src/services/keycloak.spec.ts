import { beforeEach, describe, expect, it, vi } from 'vitest'
import { obterTokenDeAcesso } from './keycloak'

const cliente = vi.hoisted(() => ({
  token: undefined as string | undefined,
  updateToken: vi.fn<(minValidity: number) => Promise<boolean>>(),
}))

vi.mock('keycloak-js', () => ({
  default: vi.fn<() => typeof cliente>(function () { return cliente }),
}))

beforeEach(() => {
  cliente.token = 'token-atual'
  cliente.updateToken.mockReset().mockResolvedValue(false)
})

describe('renovação do token', () => {
  it('aguarda a renovação e devolve o novo token', async () => {
    let concluirRenovacao!: (valor: boolean) => void
    const renovacao = new Promise<boolean>((resolve) => { concluirRenovacao = resolve })
    cliente.updateToken.mockReturnValue(renovacao)

    const token = obterTokenDeAcesso()
    expect(cliente.updateToken).toHaveBeenCalledWith(30)
    cliente.token = 'token-renovado'
    concluirRenovacao(true)

    await expect(token).resolves.toBe('token-renovado')
  })

  it('reutiliza o token quando o adaptador confirma sua validade', async () => {
    await expect(obterTokenDeAcesso()).resolves.toBe('token-atual')
  })

  it('não tenta renovar antes do login', async () => {
    cliente.token = undefined
    await expect(obterTokenDeAcesso()).resolves.toBeUndefined()
    expect(cliente.updateToken).not.toHaveBeenCalled()
  })

  it('não devolve token antigo quando a renovação falha por indisponibilidade', async () => {
    cliente.updateToken.mockRejectedValue(new Error('Indisponível'))
    await expect(obterTokenDeAcesso()).rejects.toThrow('Indisponível')
    expect(cliente.token).toBe('token-atual')
  })

  it('devolve sessão ausente quando o adaptador invalida o refresh token', async () => {
    cliente.updateToken.mockImplementation(async () => {
      cliente.token = undefined
      throw new Error('Sessão expirada')
    })
    await expect(obterTokenDeAcesso()).resolves.toBeUndefined()
  })
})
