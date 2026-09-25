import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import roteador from './index'
import { usarStoreSessao } from '@/stores/session'
import { RouterView } from 'vue-router'
import { apiClient } from '@/services/api'
import { abrirAcompanhamentoJob } from '@/services/jobEvents'
import { jobFixture, regraFixture, respostaPendente } from '@/services/job.fixtures'
import type { Job } from '@/types/api'

vi.mock('@/services/api', () => ({
  apiClient: {
    consultarJob: vi.fn<typeof apiClient.consultarJob>(),
    listarJobs: vi.fn<typeof apiClient.listarJobs>(),
  },
}))
vi.mock('@/services/jobEvents', () => ({
  abrirAcompanhamentoJob: vi.fn<typeof abrirAcompanhamentoJob>(),
}))

enableAutoUnmount(afterEach)

describe('roteador', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('resolve a raiz para a view de bootstrap', () => {
    expect(roteador.resolve('/').name).toBe('bootstrap')
  })

  it('inicia o login do Keycloak ao acessar uma rota de negócio sem sessão', async () => {
    const entrar = vi.spyOn(usarStoreSessao(), 'entrar').mockResolvedValue()

    await roteador.push('/nova-regra')

    expect(entrar).toHaveBeenCalledWith('/nova-regra')
  })

  it('permite uma rota de negócio para um usuário autenticado', async () => {
    usarStoreSessao().estaAutenticado = true

    await roteador.push('/nova-regra')

    expect(roteador.currentRoute.value.name).toBe('nova-regra')
  })
})

describe('navegação entre simulação e finalização', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(apiClient.consultarJob).mockResolvedValue(jobFixture())
    vi.mocked(apiClient.listarJobs).mockResolvedValue({
      itens: [], pagina: 0, tamanho: 100, total: 0,
    })
    vi.mocked(abrirAcompanhamentoJob).mockImplementation(() => ({
      fechar: vi.fn<() => void>(),
    }))
  })

  async function montarFluxo(caminho: string) {
    const pinia = createPinia()
    setActivePinia(pinia)
    usarStoreSessao().estaAutenticado = true
    await roteador.push(caminho)
    const wrapper = mount(RouterView, {
      global: {
        plugins: [pinia, roteador],
        stubs: { TheSidebar: true, TheProcessHeader: true, FontAwesomeIcon: true },
      },
    })
    await flushPromises()
    return wrapper
  }

  it('carrega a regra ao seguir para a finalização pelo botão sem recarregar a página', async () => {
    const wrapper = await montarFluxo('/jobs/job-1')
    const consultaFinalizacao = respostaPendente<Job>()
    vi.mocked(apiClient.consultarJob).mockReturnValueOnce(consultaFinalizacao.promise)

    await wrapper.findAll('button').find((botao) => botao.text() === 'Seguir para Finalização')!.trigger('click')
    await vi.waitFor(() => expect(roteador.currentRoute.value.name).toBe('finalizar'))
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('Finalizar Regra')
    expect(wrapper.text()).toContain('Carregando dados da regra...')

    const recente = regraFixture(2)
    recente.representacao.nucleo.loja = ['Loja atualizada na finalização']
    consultaFinalizacao.resolve(jobFixture({ regras: [regraFixture(), recente] }))
    await flushPromises()

    expect(wrapper.text()).not.toContain('Carregando dados da regra...')
    expect(wrapper.text()).toContain('Loja atualizada na finalização')
    expect(wrapper.text()).toContain('482.000,00')
    const botaoSalvar = wrapper.findAll('button').find((botao) => botao.text() === 'Salvar')!
    const botaoArquivar = wrapper.findAll('button').find((botao) => botao.text() === 'Arquivar')!
    expect(botaoSalvar.attributes('disabled')).toBeUndefined()
    expect(botaoArquivar.attributes('disabled')).toBeUndefined()
    expect(abrirAcompanhamentoJob).toHaveBeenCalledTimes(2)
    const [simulacao, finalizacao] = vi.mocked(abrirAcompanhamentoJob).mock.results
    expect(simulacao!.value.fechar).toHaveBeenCalledOnce()
    expect(finalizacao!.value.fechar).not.toHaveBeenCalled()

    wrapper.unmount()
    expect(finalizacao!.value.fechar).toHaveBeenCalledOnce()
  })

  it('carrega a simulação ao sair da finalização mantendo o novo acompanhamento ativo', async () => {
    const wrapper = await montarFluxo('/jobs/job-1/finalizar')
    expect(wrapper.text()).not.toContain('Carregando dados da regra...')
    const consultaSimulacao = respostaPendente<Job>()
    vi.mocked(apiClient.consultarJob).mockReturnValueOnce(consultaSimulacao.promise)

    await roteador.push('/jobs/job-1')
    await flushPromises()
    const recente = regraFixture(2)
    recente.representacao.nucleo.loja = ['Loja atualizada na simulação']
    consultaSimulacao.resolve(jobFixture({ regras: [regraFixture(), recente] }))
    await flushPromises()

    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.get('#loja').element).toHaveProperty('value', 'Loja atualizada na simulação')
    expect(wrapper.text()).toContain('Resultado: Regra de negócio aprovada!')
    expect(abrirAcompanhamentoJob).toHaveBeenCalledTimes(2)
    const [finalizacao, simulacao] = vi.mocked(abrirAcompanhamentoJob).mock.results
    expect(finalizacao!.value.fechar).toHaveBeenCalledOnce()
    expect(simulacao!.value.fechar).not.toHaveBeenCalled()

    wrapper.unmount()
    expect(simulacao!.value.fechar).toHaveBeenCalledOnce()
  })
})
