import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { jobComTentativasFixture } from '@/services/job.fixtures'
import SugestaoRegra from './SugestaoRegra.vue'

describe('SugestaoRegra', () => {
  const job = jobComTentativasFixture()
  function montar(status = job.status, veredito = job.simulacao!.veredito) {
    return mount(SugestaoRegra, {
      props: {
        regra: job.regras[0]!,
        simulacao: { ...job.simulacao!, veredito },
        status,
        meta: 'Não informada',
        podeAceitar: true,
        podeCancelar: true,
      },
      global: { stubs: { FontAwesomeIcon: true, RouterLink: { template: '<a><slot /></a>' } } },
    })
  }
  it('apresenta a taxa viável e emite as ações existentes', async () => {
    const wrapper = montar()
    expect(wrapper.get('#percentual-sugestao').element).toHaveProperty('value', '2%')
    await wrapper.findAll('button')[0]!.trigger('click')
    await wrapper.findAll('button')[1]!.trigger('click')
    expect(wrapper.emitted('aceitar')).toHaveLength(1)
    expect(wrapper.emitted('cancelar')).toHaveLength(1)
  })
  it.each(['gerando_regra', 'simulando', 'simulacao_inviavel'] as const)(
    'não apresenta a tentativa durante %s',
    (status) => {
      const wrapper = montar(status, 'inviavel')
      expect(wrapper.find('#total-sugestao').exists()).toBe(false)
      expect(wrapper.find('button').exists()).toBe(false)
      expect(wrapper.text()).not.toMatch(/tentativa|veredito|proposito|480.500/)
      expect(wrapper.text().includes('Iniciar nova regra')).toBe(status === 'simulacao_inviavel')
    },
  )
})
