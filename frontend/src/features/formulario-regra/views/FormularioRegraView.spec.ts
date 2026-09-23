import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import FormularioRegraView from './FormularioRegraView.vue'

vi.mock('@/services/api', () => ({
  apiClient: {
    criarJob: vi.fn<() => Promise<unknown>>(),
    listarJobs: vi.fn<() => Promise<unknown>>().mockResolvedValue({
      itens: [
        {
          id: 'job-1',
          status: 'aguardando_confirmacao_parametros',
          competencias: ['2025-09'],
          orcamento: 485000,
          criado_em: '2026-09-17T12:00:00Z',
        },
        {
          id: 'job-2',
          status: 'arquivado',
          competencias: ['2025-09'],
          orcamento: 485000,
          criado_em: '2026-09-16T12:00:00Z',
        },
      ],
      pagina: 0,
      tamanho: 100,
      total: 2,
    }),
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn<(destino: string) => Promise<void>>(),
    resolve: vi.fn<(destino: string) => { name: string }>(),
  }),
}))

const opcoesDeMontagem = {
  global: {
    plugins: [createPinia()],
    stubs: {
      RouterLink: {
        props: ['to'],
        template: '<a :href="to"><slot /></a>',
      },
    },
  },
}

describe('FormularioRegraView', () => {
  it('carrega as regras recentes pela API', async () => {
    const conteiner = mount(FormularioRegraView, opcoesDeMontagem)

    await vi.waitFor(() => {
      expect(conteiner.text()).toContain('Regra · 17/09/2026')
      expect(conteiner.text()).toContain('Salvas1')
      expect(conteiner.text()).toContain('Arquivadas1')
    })
  })

  it('mostra a pendência no próprio campo ao tentar enviar dados vazios', async () => {
    const conteiner = mount(FormularioRegraView, opcoesDeMontagem)

    await conteiner.get('form').trigger('submit')

    expect(conteiner.get('#loja-erro').text()).toBe('Informe ao menos um código de loja.')
    expect(conteiner.get('#loja').attributes('aria-invalid')).toBe('true')
  })
})
