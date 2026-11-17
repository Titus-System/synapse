import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { usarStoreSessao } from '@/stores/session'
import { HttpError } from '@/services/http'
import { auditoriaApi } from '../services/auditoria.api'
import { registroExemplo } from '../auditoria.fixture'
import DossiesView from './DossiesView.vue'
import DossieView from './DossieView.vue'
vi.mock('../services/auditoria.api', () => ({
  auditoriaApi: {
    listar: vi.fn<typeof auditoriaApi.listar>(),
    obter: vi.fn<typeof auditoriaApi.obter>(),
  },
}))
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
  vi.mocked(auditoriaApi.obter).mockResolvedValue(registroExemplo())
  vi.mocked(auditoriaApi.listar).mockResolvedValue({
    itens: [registroExemplo().job],
    pagina: 0,
    tamanho: 12,
    total: 20,
  })
})
afterEach(() => {
  wrapper?.unmount()
  vi.restoreAllMocks()
})
async function abrir(path = '/auditoria/dossies') {
  const pinia = createPinia()
  usarStoreSessao(pinia).papel = 'auditor'
  usarStoreSessao(pinia).login = 'auditor.teste'
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/auditoria/dossies', component: DossiesView },
      { path: '/auditoria/dossies/:id', name: 'auditoria-dossie', component: DossieView },
    ],
  })
  await router.push(path)
  await router.isReady()
  wrapper = mount(path === '/auditoria/dossies' ? DossiesView : DossieView, {
    global: { plugins: [pinia, router] },
  })
  return router
}
it('lista dados de outro usuário e troca de página sem consultar detalhes', async () => {
  await abrir()
  await flushPromises()
  expect(wrapper!.text()).toContain('rh.outro')
  expect(wrapper!.text()).toContain('20 resultados')
  expect(wrapper!.text()).toContain('auditor.teste')
  await wrapper!
    .findAll('button')
    .find((b) => b.text().includes('Próxima'))!
    .trigger('click')
  await flushPromises()
  expect(auditoriaApi.listar).toHaveBeenLastCalledWith(1, 12, expect.any(AbortSignal))
  expect(auditoriaApi.obter).not.toHaveBeenCalled()
})
it('mostra lista vazia', async () => {
  vi.mocked(auditoriaApi.listar).mockResolvedValue({ itens: [], pagina: 0, tamanho: 12, total: 0 })
  await abrir()
  await flushPromises()
  expect(wrapper!.text()).toContain('Nenhum dossiê encontrado')
})
it.each([
  ['sem_permissao', 'Acesso negado'],
  ['job_nao_encontrado', 'Dossiê não encontrado'],
] as const)('mapeia %s sem expor corpo', async (code, mensagem) => {
  vi.mocked(auditoriaApi.obter).mockRejectedValue(new HttpError(403, 'segredo', { code }))
  await abrir('/auditoria/dossies/job-1')
  await flushPromises()
  expect(wrapper!.get('[role="alert"]').text()).toContain(mensagem)
  expect(wrapper!.text()).not.toContain('segredo')
  const linha = JSON.parse(vi.mocked(console.error).mock.calls[0]![0] as string)
  expect(linha).toMatchObject({
    level: 'ERROR',
    'service.name': 'synapse-frontend',
    job_id: 'job-1',
    extra: { operacao: 'consultar_dossie', codigo: code, resultado: 'falha' },
  })
  expect(JSON.stringify(linha)).not.toContain('segredo')
})
it('permite tentar novamente após falha de listagem', async () => {
  vi.mocked(auditoriaApi.listar).mockRejectedValueOnce(new Error('segredo'))
  await abrir()
  await flushPromises()
  expect(wrapper!.get('[role="alert"]').text()).not.toContain('segredo')
  await wrapper!
    .findAll('button')
    .find((b) => b.text() === 'Tentar novamente')!
    .trigger('click')
  await flushPromises()
  expect(wrapper!.text()).toContain('Comissão de novembro')
})
it('exibe HTML como texto, códigos e referências; abas não repetem consulta', async () => {
  const router = await abrir('/auditoria/dossies/job-1?aba=regra')
  await flushPromises()
  expect(wrapper!.text()).toContain('<img src=x onerror=alert(1)>')
  expect(wrapper!.find('img[src="x"]').exists()).toBe(false)
  expect(wrapper!.text()).toContain('loja = 13')
  expect(wrapper!.text()).toContain('marca = 10')
  expect(wrapper!.text()).toContain('cargo = 100')
  expect(wrapper!.text()).toContain('Código codigo-1')
  expect(wrapper!.text()).toContain('Entrada entrada-1')
  expect(wrapper!.text()).toContain('09:00:00')
  await wrapper!
    .findAll('button')
    .find((b) => b.text() === 'Conversa e Python')!
    .trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query.aba).toBe('conversa')
  expect(auditoriaApi.obter).toHaveBeenCalledTimes(1)
  await router.push('/auditoria/dossies/job-2?aba=regra')
  await flushPromises()
  expect(auditoriaApi.obter).toHaveBeenCalledTimes(2)
})
it('abre aba indicada no endereço', async () => {
  await abrir('/auditoria/dossies/job-1?aba=simulacoes')
  await flushPromises()
  expect(wrapper!.text()).toContain('Esta seção ainda não está disponível')
  expect(wrapper!.find('blockquote').exists()).toBe(false)
})
it('mostra formulário e ausência de versões', async () => {
  const registro = registroExemplo()
  registro.entradas[0]!.tipo = 'formulario'
  registro.entradas[0]!.conteudo = { observacao: '<script>alert(1)</script>' }
  registro.versoes = []
  vi.mocked(auditoriaApi.obter).mockResolvedValue(registro)
  await abrir('/auditoria/dossies/job-1')
  await flushPromises()
  expect(wrapper!.text()).toContain('<script>alert(1)</script>')
  expect(wrapper!.find('script').exists()).toBe(false)
  expect(wrapper!.text()).toContain('Nenhuma versão registrada')
})

it('mostra carregamento enquanto a consulta está pendente', async () => {
  vi.mocked(auditoriaApi.listar).mockImplementation(() => new Promise(() => undefined))
  await abrir()
  expect(wrapper!.get('[role="status"]').text()).toContain('Carregando dossiês')
})
