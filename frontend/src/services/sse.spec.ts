import { describe, expect, it, vi } from 'vitest'
import { consumirEventosSse } from './sse'

function corpo(fragmentos: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(controlador) {
      fragmentos.forEach((fragmento) => controlador.enqueue(fragmento))
      controlador.close()
    },
  })
}

describe('leitura de SSE', () => {
  it.each(['\n', '\r\n', '\r'])('lê UTF-8, comentários e várias linhas data com separador %j', async (separador) => {
    const texto = [
      '\uFEFF: heartbeat', '',
      'event: estado', 'id: 1', 'data: {"mensagem":', 'data: "geração"}', '',
      ': heartbeat', '',
      'event: etapa', 'data: {"etapa":"simulação"}', '', '',
    ].join(separador)
    const bytes = new TextEncoder().encode(texto)
    const receber = vi.fn<(evento: string, dados: string) => void>()

    await consumirEventosSse(corpo(Array.from(bytes, (byte) => new Uint8Array([byte]))), receber)

    expect(receber.mock.calls).toEqual([
      ['estado', '{"mensagem":\n"geração"}'],
      ['etapa', '{"etapa":"simulação"}'],
    ])
  })

  it('não publica um evento incompleto no fim do stream', async () => {
    const receber = vi.fn<(evento: string, dados: string) => void>()
    await consumirEventosSse(corpo([new TextEncoder().encode('event: estado\ndata: {}\n')]), receber)
    expect(receber).not.toHaveBeenCalled()
  })

  it('lê vários eventos no mesmo fragmento e reinicia o nome após cada bloco', async () => {
    const receber = vi.fn<(evento: string, dados: string) => void>()
    await consumirEventosSse(corpo([new TextEncoder().encode('event: estado\ndata: um\n\ndata: dois\n\n')]), receber)
    expect(receber.mock.calls).toEqual([['estado', 'um'], ['message', 'dois']])
  })
})
