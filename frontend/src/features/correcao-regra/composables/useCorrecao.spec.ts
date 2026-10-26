import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from '@/services/api'
import { abrirAcompanhamentoJob } from '@/services/jobEvents'
import { HttpError } from '@/services/http'
import * as api from '../services/correcao.api'
import { jobCorrecao, pendente, rodadaVoz, vozCriada } from '../services/correcao.fixtures'
import { useCorrecao } from './useCorrecao'
vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: vi.fn<() => { fechar: () => void }>(() => ({
    fechar: vi.fn<() => void>(),
  })),
}))
vi.mock('../services/correcao.api', () => ({
  listarRodadas: vi.fn<typeof import('../services/correcao.api').listarRodadas>(),
  enviarCorrecaoVoz: vi.fn<typeof import('../services/correcao.api').enviarCorrecaoVoz>(),
  enviarCorrecaoTexto: vi.fn<typeof import('../services/correcao.api').enviarCorrecaoTexto>(),
}))
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.useFakeTimers()
  vi.spyOn(console, 'info').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.spyOn(apiClient, 'consultarJob').mockImplementation(async () => structuredClone(jobCorrecao))
  vi.mocked(api.listarRodadas).mockResolvedValue([pendente])
  vi.mocked(api.enviarCorrecaoVoz).mockResolvedValue(vozCriada)
})
afterEach(() => {
  wrappers.splice(0).forEach((w) => w.unmount())
  vi.restoreAllMocks()
  vi.clearAllMocks()
  vi.useRealTimers()
})
async function montar(id = ref(jobCorrecao.id)) {
  let fluxo!: ReturnType<typeof useCorrecao>
  wrappers.push(
    mount({
      setup() {
        fluxo = useCorrecao(id)
        return () => null
      },
    }),
  )
  await flushPromises()
  return { fluxo, id }
}
const handlers = () =>
  vi.mocked(abrirAcompanhamentoJob).mock.calls[
    vi.mocked(abrirAcompanhamentoJob).mock.calls.length - 1
  ]![1]
it('bloqueia envio vazio e duplicado; mantém rascunho durante transcrição', async () => {
  const { fluxo } = await montar()
  fluxo.texto.value = 'rascunho privado'
  await fluxo.enviar(new Blob())
  expect(api.enviarCorrecaoVoz).not.toHaveBeenCalled()
  const envio = fluxo.enviar(new Blob(['audio privado']))
  await fluxo.enviar(new Blob(['audio duplicado']))
  await envio
  expect(api.enviarCorrecaoVoz).toHaveBeenCalledOnce()
  expect(fluxo.habilitada.value).toBe(false)
  expect(fluxo.rodadas.value).toEqual([rodadaVoz])
  expect(fluxo.texto.value).toBe('rascunho privado')
  expect(JSON.stringify(vi.mocked(console.info).mock.calls)).not.toMatch(
    /rascunho privado|audio privado|percentual ausente/,
  )
})
it('restaura transcrição pelo GET e consulta até aparecer texto, sem SSE', async () => {
  vi.mocked(api.listarRodadas).mockResolvedValue([rodadaVoz])
  const { fluxo } = await montar()
  expect(fluxo.habilitada.value).toBe(false)
  vi.mocked(api.listarRodadas).mockResolvedValue([
    {
      ...rodadaVoz,
      estado: 'em_reextracao',
      correcao: { ...rodadaVoz.correcao!, texto: 'percentual 2,5%' },
    },
  ])
  await vi.advanceTimersByTimeAsync(3000)
  expect(fluxo.rodadas.value[0]?.correcao?.texto).toBe('percentual 2,5%')
  expect(fluxo.habilitada.value).toBe(false)
})
it('falha da transcrição e nova pendente liberam voz e texto', async () => {
  vi.mocked(api.listarRodadas).mockResolvedValue([rodadaVoz])
  const { fluxo } = await montar()
  vi.mocked(api.listarRodadas).mockResolvedValue([
    { ...rodadaVoz, estado: 'reextracao_falhou' },
    { ...pendente, id: 'nova', rodada_anterior_id: rodadaVoz.id },
  ])
  handlers().onReconciliar()
  await flushPromises()
  expect(fluxo.habilitada.value).toBe(true)
  fluxo.texto.value = 'nova tentativa'
  expect(fluxo.podeEnviar.value).toBe(true)
})
it('reconexão e eventos repetidos reconstroem sem duplicar mensagens ou envio', async () => {
  vi.mocked(api.listarRodadas).mockResolvedValue([rodadaVoz])
  const { fluxo } = await montar()
  handlers().onReconciliar()
  handlers().onReconciliar()
  handlers().onEtapa({ job_id: jobCorrecao.id, etapa: 'extracao_parametros', status: 'erro' })
  await flushPromises()
  expect(fluxo.rodadas.value).toEqual([rodadaVoz])
  expect(api.enviarCorrecaoVoz).not.toHaveBeenCalled()
})
it.each(['audio_invalido', 'audio_muito_grande', 'estado_invalido'] as const)(
  'registra falha sanitizada %s, reconcilia e permite tentar texto',
  async (code) => {
    const { fluxo } = await montar()
    vi.mocked(api.enviarCorrecaoVoz).mockRejectedValue(
      new HttpError(409, 'excecao privada', { code }),
    )
    await fluxo.enviar(new Blob(['audio privado']))
    expect(fluxo.erroEnvio.value).not.toContain('excecao privada')
    expect(fluxo.habilitada.value).toBe(true)
    const registros = vi.mocked(console.error).mock.calls.map((call) => JSON.parse(String(call[0])))
    expect(registros).toContainEqual(
      expect.objectContaining({
        job_id: jobCorrecao.id,
        extra: expect.objectContaining({ operacao: 'enviar_correcao_voz', codigo: code }),
      }),
    )
    expect(JSON.stringify(registros)).not.toMatch(/excecao privada|audio privado/)
  },
)
it('mantém texto vazio/longos bloqueados e envia alternativa válida', async () => {
  const { fluxo } = await montar()
  fluxo.texto.value = ' '.repeat(3)
  await fluxo.enviar()
  fluxo.texto.value = 'x'.repeat(4001)
  await fluxo.enviar()
  expect(api.enviarCorrecaoTexto).not.toHaveBeenCalled()
  vi.mocked(api.enviarCorrecaoTexto).mockResolvedValue({
    ...vozCriada,
    tipo: 'texto',
    rodada: {
      ...rodadaVoz,
      estado: 'em_reextracao',
      correcao: { texto: 'correcao', enviada_em: rodadaVoz.criada_em },
    },
  })
  fluxo.texto.value = ' correcao '
  await fluxo.enviar()
  expect(api.enviarCorrecaoTexto).toHaveBeenCalledWith(
    jobCorrecao.id,
    'correcao',
    expect.any(AbortSignal),
  )
  expect(fluxo.texto.value).toBe('')
})
it('troca de job limpa correlação, rascunho, mídia por chave e callbacks antigos', async () => {
  const { fluxo, id } = await montar()
  const antigos = handlers()
  const sinal = vi.mocked(api.listarRodadas).mock.calls[0]![1]
  fluxo.texto.value = 'privado'
  id.value = 'outro-job'
  await flushPromises()
  expect(sinal.aborted).toBe(true)
  expect(fluxo.texto.value).toBe('')
  vi.mocked(console.info).mockClear()
  antigos.onReconciliar()
  antigos.onStatusConexao('reconectando')
  await fluxo.enviar(new Blob(['audio']))
  const registros = vi.mocked(console.info).mock.calls.map((c) => JSON.parse(String(c[0])))
  expect(registros).toHaveLength(1)
  expect(registros[0].job_id).toBe('outro-job')
})
it('resposta tardia de envio não contamina o próximo job', async () => {
  const { fluxo, id } = await montar()
  let concluir!: (value: typeof vozCriada) => void
  vi.mocked(api.enviarCorrecaoVoz).mockReturnValue(
    new Promise((resolve) => {
      concluir = resolve
    }),
  )
  const envio = fluxo.enviar(new Blob(['audio']))
  id.value = 'outro-job'
  await flushPromises()
  concluir(vozCriada)
  await envio
  expect(fluxo.rodadas.value).toEqual([pendente])
  expect(fluxo.enviando.value).toBe(false)
})
it('falha de leitura bloqueia envio até recuperar, sem expor exceção', async () => {
  vi.mocked(api.listarRodadas).mockRejectedValue(new Error('segredo'))
  const { fluxo } = await montar()
  expect(fluxo.habilitada.value).toBe(false)
  expect(fluxo.erroLeitura.value).not.toContain('segredo')
  vi.mocked(api.listarRodadas).mockResolvedValue([pendente])
  await fluxo.atualizar()
  expect(fluxo.habilitada.value).toBe(true)
})
it('ignora leitura antiga que termina depois do POST aceito', async () => {
  const { fluxo } = await montar()
  let concluir!: (value: (typeof pendente)[]) => void
  vi.mocked(api.listarRodadas).mockReturnValueOnce(
    new Promise((resolve) => {
      concluir = resolve
    }),
  )
  const leitura = fluxo.atualizar()
  await fluxo.enviar(new Blob(['audio']))
  concluir([pendente])
  await leitura
  expect(fluxo.rodadas.value).toEqual([rodadaVoz])
})
it('desmontagem fecha SSE, cancela HTTP e polling', async () => {
  vi.mocked(api.listarRodadas).mockResolvedValue([rodadaVoz])
  await montar()
  const fechar =
    vi.mocked(abrirAcompanhamentoJob).mock.results[
      vi.mocked(abrirAcompanhamentoJob).mock.results.length - 1
    ]!.value.fechar
  wrappers[0]!.unmount()
  vi.mocked(api.listarRodadas).mockClear()
  await vi.advanceTimersByTimeAsync(10000)
  expect(fechar).toHaveBeenCalled()
  expect(api.listarRodadas).not.toHaveBeenCalled()
})
it('não devolve ao progresso o job que aguarda correção sem rodada aberta', async () => {
  vi.mocked(api.listarRodadas).mockResolvedValue([])
  const { fluxo } = await montar()
  expect(fluxo.semCorrecao.value).toBe(true)
  expect(fluxo.seguirProcessamento.value).toBe(false)
  expect(fluxo.habilitada.value).toBe(false)
})
it('volta ao progresso quando a correção leva o job adiante', async () => {
  vi.mocked(api.listarRodadas).mockResolvedValue([{ ...pendente, estado: 'corrigida' }])
  vi.mocked(apiClient.consultarJob).mockResolvedValue({
    ...structuredClone(jobCorrecao),
    status: 'gerando_regra',
  })
  const { fluxo } = await montar()
  expect(fluxo.seguirProcessamento.value).toBe(true)
  expect(fluxo.semCorrecao.value).toBe(false)
})
