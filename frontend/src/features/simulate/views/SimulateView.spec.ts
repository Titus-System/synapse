import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SimulateView from './SimulateView.vue'

describe('SimulateView', () => {
  it('renderiza a tela de simulação', () => {
    const conteiner = mount(SimulateView)

    expect(conteiner.get('h1').text()).toBe('Simulação')
    expect(conteiner.text()).toContain('Simule uma regra de negócio.')
  })
})