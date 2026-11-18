import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter, createWebHistory } from 'vue-router'
import { usarStoreSessao } from '@/stores/session'
import { HttpError } from '@/services/http'
import { auditoriaApi } from '../services/auditoria.api'
import { eventoExemplo, paginaEventosExemplo, registroExemplo } from '../auditoria.fixture'
import DossiesView from './DossiesView.vue'
import DossieView from './DossieView.vue'
vi.mock('../services/auditoria.api', () => ({
  auditoriaApi: {
    listar: vi.fn<typeof auditoriaApi.listar>(),
    obter: vi.fn<typeof auditoriaApi.obter>(),
    listarEventos: vi.fn<typeof auditoriaApi.listarEventos>(),
    obterAudio: vi.fn<typeof auditoriaApi.obterAudio>(),
  },
}))
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.clearAllMocks()
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
  vi.mocked(auditoriaApi.obter).mockResolvedValue(registroExemplo())
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(paginaEventosExemplo())
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
      { path: '/auditoria', name: 'auditoria-operacoes', component: { render: () => null } },
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
it('baixa o áudio só quando o auditor pede e não o mantém ao trocar de job', async () => {
  URL.createObjectURL = vi.fn<(objeto: Blob) => string>(() => 'blob:audio-job-1')
  URL.revokeObjectURL = vi.fn<(url: string) => void>()
  const registro = registroExemplo()
  Object.assign(registro.entradas[0]!, { tipo: 'voz', formato: 'ogg', texto: 'Transcrição' })
  vi.mocked(auditoriaApi.obter).mockResolvedValue(registro)
  vi.mocked(auditoriaApi.obterAudio).mockResolvedValue({
    conteudo: new Blob(['audio']),
    tipo: 'audio/ogg',
  })
  const router = await abrir('/auditoria/dossies/job-1?aba=regra')
  await flushPromises()
  expect(auditoriaApi.obterAudio).not.toHaveBeenCalled()

  await wrapper!.get('[data-reprodutor-audio] button').trigger('click')
  await flushPromises()
  expect(auditoriaApi.obterAudio).toHaveBeenCalledExactlyOnceWith(
    'job-1',
    'entrada-1',
    expect.any(AbortSignal),
  )
  expect(wrapper!.get('audio').attributes('src')).toBe('blob:audio-job-1')

  await router.push('/auditoria/dossies/job-2?aba=regra')
  await flushPromises()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:audio-job-1')
  expect(wrapper!.find('audio').exists()).toBe(false)
  expect(wrapper!.find('[data-reprodutor-audio] button').exists()).toBe(true)
  expect(auditoriaApi.obterAudio).toHaveBeenCalledTimes(1)
})
it('abre aba indicada no endereço', async () => {
  await abrir('/auditoria/dossies/job-1?aba=conversa')
  await flushPromises()
  expect(wrapper!.text()).toContain('Conversa completa')
  expect(wrapper!.text()).not.toContain('Esta seção ainda não está disponível')
  expect(wrapper!.find('img[onerror]').exists()).toBe(false)
})
it('mostra a trilha do job em ordem cronológica na aba de simulações', async () => {
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(
    paginaEventosExemplo([
      eventoExemplo({
        instante: '2026-11-03T12:05:00Z',
        tipo: 'acao_usuario',
        autor: 'usuario',
        origem_id: 'acao-1',
        acao: 'salvar',
        status: undefined,
        veredito: undefined,
      }),
      eventoExemplo({ instante: '2026-11-03T12:02:00Z', origem_id: 'resultado-1' }),
      eventoExemplo({
        instante: '2026-11-03T12:00:00Z',
        tipo: 'entrada',
        autor: 'usuario',
        origem_id: 'entrada-1',
        finalidade: 'entrada_inicial',
        tipo_entrada: 'texto',
        status: undefined,
        veredito: undefined,
      }),
    ]),
  )
  await abrir('/auditoria/dossies/job-1?aba=simulacoes')
  await flushPromises()
  expect(auditoriaApi.listarEventos).toHaveBeenCalledWith(
    { regra: 'job-1' },
    0,
    100,
    expect.any(AbortSignal),
  )
  const itens = wrapper!.findAll('ol[aria-label="Trilha cronológica"] li').map((li) => li.text())
  expect(itens).toHaveLength(3)
  expect(itens[0]).toBe(
    '03/11/202609:00:00Entrada · Entrada inicial · Textorh.outro · Registro entrada-1',
  )
  expect(itens[1]).toContain('Simulação · Sucesso · Viável')
  expect(itens[1]).toContain('Sistema · Registro resultado-1')
  expect(itens[2]).toContain('Ação do usuário · Salvarrh.outro · Registro acao-1')
  expect(wrapper!.text()).not.toContain('Esta seção ainda não está disponível')
})
it('só consulta a trilha ao abrir a aba de simulações, uma vez por job', async () => {
  const router = await abrir('/auditoria/dossies/job-1?aba=regra')
  await flushPromises()
  expect(auditoriaApi.listarEventos).not.toHaveBeenCalled()
  await wrapper!
    .findAll('button')
    .find((b) => b.text() === 'Simulações e finalização')!
    .trigger('click')
  await flushPromises()
  expect(auditoriaApi.listarEventos).toHaveBeenCalledTimes(1)
  await router.replace({ query: { aba: 'regra' } })
  await router.replace({ query: { aba: 'simulacoes' } })
  await flushPromises()
  expect(auditoriaApi.listarEventos).toHaveBeenCalledTimes(1)
  await router.push('/auditoria/dossies/job-2?aba=simulacoes')
  await flushPromises()
  expect(auditoriaApi.listarEventos).toHaveBeenLastCalledWith(
    { regra: 'job-2' },
    0,
    100,
    expect.any(AbortSignal),
  )
})
it('mostra a trilha vazia', async () => {
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(paginaEventosExemplo([]))
  await abrir('/auditoria/dossies/job-1?aba=simulacoes')
  await flushPromises()
  expect(wrapper!.text()).toContain('Nenhum evento registrado para esta regra.')
})
it('registra a falha da trilha com o job e permite tentar novamente', async () => {
  vi.mocked(auditoriaApi.listarEventos).mockRejectedValueOnce(
    new HttpError(403, 'segredo', { code: 'sem_permissao' }),
  )
  await abrir('/auditoria/dossies/job-1?aba=simulacoes')
  await flushPromises()
  expect(wrapper!.get('[role="alert"]').text()).toContain('Acesso negado')
  const linha = JSON.parse(vi.mocked(console.error).mock.calls[0]![0] as string)
  expect(linha).toMatchObject({
    level: 'ERROR',
    job_id: 'job-1',
    extra: { operacao: 'listar_trilha_dossie', codigo: 'sem_permissao', resultado: 'falha' },
  })
  await wrapper!
    .findAll('button')
    .find((b) => b.text() === 'Tentar novamente')!
    .trigger('click')
  await flushPromises()
  expect(wrapper!.find('ol[aria-label="Trilha cronológica"]').exists()).toBe(true)
})
it('volta ao painel com os filtros quando chegou por ele', async () => {
  const pinia = createPinia()
  usarStoreSessao(pinia).papel = 'auditor'
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/auditoria', name: 'auditoria-operacoes', component: { render: () => null } },
      { path: '/auditoria/dossies', component: { render: () => null } },
      { path: '/auditoria/dossies/:id', name: 'auditoria-dossie', component: DossieView },
    ],
  })
  await router.push('/auditoria?usuario=rh.outro&mes=2026-10')
  await router.push('/auditoria/dossies/job-1?aba=simulacoes')
  wrapper = mount(DossieView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  const voltar = wrapper.findAll('a').find((a) => a.text().startsWith('←'))!
  expect(voltar.text()).toBe('← Todas as operações')
  expect(voltar.attributes('href')).toBe('/auditoria?usuario=rh.outro&mes=2026-10')
  await wrapper!
    .findAll('button')
    .find((b) => b.text() === 'Regra e versões')!
    .trigger('click')
  await flushPromises()
  expect(
    wrapper
      .findAll('a')
      .find((a) => a.text().startsWith('←'))!
      .attributes('href'),
  ).toBe('/auditoria?usuario=rh.outro&mes=2026-10')
})
it('volta aos dossiês quando não chegou pelo painel', async () => {
  await abrir('/auditoria/dossies/job-1')
  await flushPromises()
  const voltar = wrapper!.findAll('a').filter((a) => a.text().startsWith('←'))
  expect(voltar.map((a) => [a.text(), a.attributes('href')])).toEqual([
    ['← Dossiês de regras', '/auditoria/dossies'],
    ['← Dossiês de regras', '/auditoria/dossies'],
  ])
  expect(wrapper!.get('[aria-current="page"]').text()).toBe('Dossiês de regras')
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
