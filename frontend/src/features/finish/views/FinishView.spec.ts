import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import FinishView from './FinishView.vue'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    {
      path: '/jobs/:id/finalizar',
      component: FinishView,
    },
  ],
})
describe('SimulateView', () => {
  it('renderiza a tela de simulação', async () => {
    await router.push('/jobs/9478cef9-07be-5ffc-ab36-758f4e819796/finalizar')
    await router.isReady()
    const conteiner = mount(FinishView, {
      global: {
        plugins: [router],
      },
    })

    expect(conteiner.get('h1').text()).toBe('Finalizar Regra')
    expect(conteiner.text()).toContain('Revise os detalhes da regra extraída e confirme o salvamento.')
  })
})