import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { HttpError, type RespostaBinaria } from '@/services/http'
import { useAudiosEntradas } from './useAudiosEntradas'

const schema = JSON.parse(
  readFileSync(
    resolve(
      dirname(fileURLToPath(import.meta.url)),
      '../../../../../contracts/observability/log.schema.json',
    ),
    'utf8',
  ),
)
type Baixar = (entradaId: string, signal: AbortSignal) => Promise<RespostaBinaria>
const conteudo = new Blob(['bytes-do-audio'], { type: 'audio/ogg' })
let urls = 0

beforeEach(() => {
  urls = 0
  URL.createObjectURL = vi.fn<(objeto: Blob) => string>(() => `blob:audio-${++urls}`)
  URL.revokeObjectURL = vi.fn<(url: string) => void>()
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
})

afterEach(() => vi.restoreAllMocks())

function montar(baixar: Baixar) {
  const jobId = ref('job-1')
  const escopo = effectScope()
  const audios = escopo.run(() => useAudiosEntradas(baixar, () => jobId.value))!
  return { ...audios, jobId, escopo }
}

function logs(nivel: 'info' | 'warn' | 'error') {
  return vi.mocked(console[nivel]).mock.calls.map(([linha]) => JSON.parse(String(linha)))
}

function adiado() {
  let resolver!: (resposta: RespostaBinaria) => void
  const promessa = new Promise<RespostaBinaria>((resolve) => {
    resolver = resolve
  })
  return { promessa, resolver }
}

describe('useAudiosEntradas', () => {
  it('não baixa nada antes de o auditor pedir para ouvir', () => {
    const baixar = vi.fn<Baixar>()
    const { audios } = montar(baixar)

    expect(baixar).not.toHaveBeenCalled()
    expect(audios.value).toEqual({})
  })

  it('baixa o áudio pedido, cria a URL local e registra o sucesso', async () => {
    const download = adiado()
    const baixar = vi.fn<Baixar>(() => download.promessa)
    const { audios, ouvir } = montar(baixar)

    const pedido = ouvir('entrada-1')
    expect(audios.value['entrada-1']).toEqual({ estado: 'carregando' })
    download.resolver({ conteudo, tipo: 'audio/ogg' })
    await pedido

    expect(baixar).toHaveBeenCalledWith('entrada-1', expect.any(AbortSignal))
    expect(URL.createObjectURL).toHaveBeenCalledWith(conteudo)
    expect(audios.value['entrada-1']).toEqual({ estado: 'pronto', url: 'blob:audio-1' })
    expect(logs('info')).toEqual([
      expect.objectContaining({
        level: 'INFO',
        message: 'Download do áudio da auditoria concluído',
        'service.name': 'synapse-frontend',
        job_id: 'job-1',
        extra: expect.objectContaining({
          operacao: 'baixar_audio_entrada',
          resultado: 'sucesso',
          codigo: 'ok',
          entrada_id: 'entrada-1',
        }),
      }),
    ])
  })

  it('não baixa de novo um áudio que já está pronto ou carregando', async () => {
    const baixar = vi.fn<Baixar>(async () => ({ conteudo, tipo: 'audio/ogg' }))
    const { ouvir } = montar(baixar)

    await Promise.all([ouvir('entrada-1'), ouvir('entrada-1')])
    await ouvir('entrada-1')

    expect(baixar).toHaveBeenCalledOnce()
  })

  it('marca como indisponível a entrada que a API não encontra', async () => {
    const { audios, ouvir } = montar(async () => {
      throw new HttpError(404, 'mensagem', { code: 'entrada_nao_encontrada' })
    })

    await ouvir('entrada-1')

    expect(audios.value['entrada-1']).toEqual({ estado: 'indisponivel' })
    expect(logs('warn')[0]).toMatchObject({
      level: 'WARN',
      job_id: 'job-1',
      extra: {
        operacao: 'baixar_audio_entrada',
        resultado: 'falha',
        codigo: 'entrada_nao_encontrada',
      },
    })
  })

  it.each([
    [new HttpError(503, 'detalhe interno do servidor'), 'falha_servico'],
    [new HttpError(0, 'sem conexão'), 'falha_rede'],
    [new HttpError(403, 'mensagem', { code: 'sem_permissao' }), 'sem_permissao'],
    [new TypeError('detalhe interno'), 'falha_inesperada'],
  ])('registra a falha %# com código fixo e mostra o estado de erro', async (falha, codigo) => {
    const { audios, ouvir } = montar(async () => {
      throw falha
    })

    await ouvir('entrada-1')

    expect(audios.value['entrada-1']).toEqual({ estado: 'erro' })
    const [registro] = logs('error')
    expect(registro).toMatchObject({
      level: 'ERROR',
      job_id: 'job-1',
      extra: { operacao: 'baixar_audio_entrada', resultado: 'falha', codigo },
    })
    expect(JSON.stringify(registro)).not.toContain('detalhe interno')
  })

  it('recusa uma resposta que não é áudio sem criar URL', async () => {
    const { audios, ouvir } = montar(async () => ({ conteudo, tipo: 'text/html' }))

    await ouvir('entrada-1')

    expect(audios.value['entrada-1']).toEqual({ estado: 'erro' })
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    expect(logs('error')[0]).toMatchObject({ extra: { codigo: 'tipo_invalido' } })
  })

  it('baixa de novo depois de um erro', async () => {
    const baixar = vi
      .fn<Baixar>()
      .mockRejectedValueOnce(new HttpError(503, 'indisponível'))
      .mockResolvedValueOnce({ conteudo, tipo: 'audio/ogg' })
    const { audios, ouvir } = montar(baixar)

    await ouvir('entrada-1')
    await ouvir('entrada-1')

    expect(baixar).toHaveBeenCalledTimes(2)
    expect(audios.value['entrada-1']).toEqual({ estado: 'pronto', url: 'blob:audio-1' })
  })

  it('registra a falha de reprodução, libera a URL e mostra o erro', async () => {
    const { audios, ouvir, falhouReproducao } = montar(async () => ({
      conteudo,
      tipo: 'audio/ogg',
    }))
    await ouvir('entrada-1')

    falhouReproducao('entrada-1')

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audio-1')
    expect(audios.value['entrada-1']).toEqual({ estado: 'erro' })
    expect(logs('error')[0]).toMatchObject({
      message: 'Reprodução do áudio da auditoria falhou',
      extra: { operacao: 'reproduzir_audio_entrada', codigo: 'falha_reproducao' },
    })
  })

  it('ao trocar de job, cancela o download pendente e libera o áudio do job anterior', async () => {
    const pendente = adiado()
    const sinais: AbortSignal[] = []
    const baixar = vi.fn<Baixar>(async (entradaId, signal) => {
      sinais.push(signal)
      return entradaId === 'entrada-1' ? { conteudo, tipo: 'audio/ogg' } : pendente.promessa
    })
    const { audios, ouvir, jobId } = montar(baixar)
    await ouvir('entrada-1')
    const atrasado = ouvir('entrada-2')

    jobId.value = 'job-2'
    await nextTick()
    pendente.resolver({ conteudo, tipo: 'audio/ogg' })
    await atrasado

    expect(sinais[1]!.aborted).toBe(true)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audio-1')
    expect(URL.createObjectURL).toHaveBeenCalledOnce()
    expect(audios.value).toEqual({})
    expect(logs('info')).toHaveLength(1)
  })

  it('libera as URLs ao sair da tela', async () => {
    const { ouvir, escopo } = montar(async () => ({ conteudo, tipo: 'audio/ogg' }))
    await ouvir('entrada-1')

    escopo.stop()

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audio-1')
  })

  it('emite logs de sucesso e de falha no envelope do schema compartilhado', async () => {
    const baixar = vi
      .fn<Baixar>()
      .mockResolvedValueOnce({ conteudo, tipo: 'audio/ogg' })
      .mockRejectedValueOnce(new HttpError(404, 'mensagem', { code: 'entrada_nao_encontrada' }))
      .mockRejectedValueOnce(new HttpError(500, 'detalhe interno'))
    const { ouvir } = montar(baixar)

    await ouvir('entrada-1')
    await ouvir('entrada-2')
    await ouvir('entrada-3')

    const linhas = [...logs('info'), ...logs('warn'), ...logs('error')]
    expect(linhas.map((linha) => linha.level)).toEqual(['INFO', 'WARN', 'ERROR'])
    for (const linha of linhas) {
      for (const campo of schema.required) expect(linha).toHaveProperty(campo)
      expect(schema.properties.level.enum).toContain(linha.level)
      expect(schema.properties['service.name'].enum).toContain(linha['service.name'])
      for (const valor of Object.values(linha.extra)) expect(typeof valor).not.toBe('object')
    }
  })

  it('não leva a URL nem o conteúdo do áudio para o log', async () => {
    const { ouvir } = montar(async () => ({ conteudo, tipo: 'audio/ogg' }))

    await ouvir('entrada-1')

    const linha = String(vi.mocked(console.info).mock.calls[0]?.[0])
    expect(linha).not.toContain('blob:')
    expect(linha).not.toContain('bytes-do-audio')
    expect(linha).not.toContain('/auditoria/')
  })
})
