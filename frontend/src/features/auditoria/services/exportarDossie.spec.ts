import { afterEach, expect, it, vi } from 'vitest'
import { registroExemplo } from '../auditoria.fixture'
import { exportarDossie } from './exportarDossie'
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
it('exporta todo o conteúdo recebido, inclusive campos desconhecidos', async () => {
  vi.useFakeTimers()
  let conteudo = ''
  let arquivo = ''
  const OriginalBlob = Blob
  vi.stubGlobal(
    'Blob',
    class extends OriginalBlob {
      constructor(partes: BlobPart[], opcoes: BlobPropertyBag) {
        super(partes, opcoes)
        conteudo = String(partes[0])
      }
    },
  )
  const criar = vi.fn<(objeto: Blob) => string>().mockReturnValue('blob:teste')
  const revogar = vi.fn<(url: string) => void>()
  vi.stubGlobal(
    'URL',
    Object.assign(class extends URL {}, { createObjectURL: criar, revokeObjectURL: revogar }),
  )
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    arquivo = this.download
  })
  const registro = { ...registroExemplo(), campo_aditivo: { preservado: true } }
  exportarDossie(registro)
  expect(JSON.parse(conteudo)).toEqual(registro)
  expect(arquivo).toBe('dossie-job-1.json')
  expect(document.querySelector('a')).toBeNull()
  await vi.runAllTimersAsync()
  expect(revogar).toHaveBeenCalledWith('blob:teste')
})
