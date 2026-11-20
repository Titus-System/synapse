import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ModeloTranscricao from './ModeloTranscricao.vue'
import type { EntradaAuditoria } from '../types'

const voz: EntradaAuditoria = {
  id: 'entrada-1',
  tipo: 'voz',
  finalidade: 'entrada_inicial',
  criado_em: '2026-11-03T12:00:00Z',
  texto: 'Comissão de 3%.',
  formato: 'ogg',
  transcrito_em: '2026-11-03T12:01:00Z',
}
const montar = (entrada: EntradaAuditoria) => mount(ModeloTranscricao, { props: { entrada } })

describe('ModeloTranscricao', () => {
  it('mostra provedor, modelo e versão de quem transcreveu', () => {
    const w = montar({
      ...voz,
      transcricao_modelo: {
        provedor: 'deepgram',
        modelo: '2-general-nova',
        versao: '2024-01-09.29447',
      },
    })
    expect(w.get('[data-modelo-transcricao]').text()).toBe(
      'Transcrito por deepgram · modelo 2-general-nova · versão 2024-01-09.29447',
    )
  })

  it('omite a versão que o provedor não informou', () => {
    const w = montar({ ...voz, transcricao_modelo: { provedor: 'deepgram', modelo: 'nova-3' } })
    expect(w.get('[data-modelo-transcricao]').text()).toBe('Transcrito por deepgram · modelo nova-3')
  })

  it('mostra o estado sem modelo na entrada transcrita antes do registro do modelo', () => {
    expect(montar(voz).get('[data-sem-modelo]').text()).toBe('Modelo da transcrição não registrado.')
  })

  it('não diz nada enquanto a transcrição está pendente nem fora da voz', () => {
    const pendente = { ...voz }
    delete pendente.texto
    delete pendente.transcrito_em
    expect(montar(pendente).text()).toBe('')
    expect(montar({ ...voz, tipo: 'texto', formato: undefined }).text()).toBe('')
  })
})
