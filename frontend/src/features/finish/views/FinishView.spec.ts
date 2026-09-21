import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import FinishView from './FinishView.vue'

describe('SimulateView', () => {
  it('renderiza a tela de simulação', () => {
    const conteiner = mount(FinishView)

    expect(conteiner.get('h1').text()).toBe('Finalizar Regra')
    expect(conteiner.text()).toContain('Revise os detalhes da regra extraída e confirme o salvamento.')
  })
})