import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MetaSugerida from './MetaSugerida.vue'

describe('MetaSugerida', () => {
  const sugestao = { meta_venda: 1200000, total_simulado: 484500, orcamento: 485000 }
  it('formata os valores recebidos e emite o aceite', async () => {
    const wrapper = mount(MetaSugerida, {
      props: { sugestao, podeAceitar: true, processando: false },
    })
    expect(wrapper.findAll('dd').map((dd) => dd.text())).toEqual([
      'R$ 1.200.000,00',
      'R$ 484.500,00',
      'R$ 485.000,00',
    ])
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('aceitar')).toHaveLength(1)
  })
  it.each([
    { podeAceitar: false, processando: false },
    { podeAceitar: true, processando: true },
  ])('bloqueia o aceite quando indisponível: %o', async (estado) => {
    const wrapper = mount(MetaSugerida, { props: { sugestao, ...estado } })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('aceitar')).toBeUndefined()
  })
  it('explica que não há meta maior sem mostrar valores ou motivo interno', () => {
    const wrapper = mount(MetaSugerida, {
      props: {
        sugestao: { sem_solucao: { motivo: 'nao_monotonica' } },
        podeAceitar: false,
        processando: false,
      },
    })
    expect(wrapper.text()).toContain('Não encontramos uma meta maior')
    expect(wrapper.text()).not.toContain('nao_monotonica')
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.find('dd').exists()).toBe(false)
  })
})
