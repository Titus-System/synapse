import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { usarStoreSessao } from '@/stores/session'
import { HttpError } from '@/services/http'
import { auditoriaApi } from '../services/auditoria.api'
import { eventoExemplo, paginaEventosExemplo } from '../auditoria.fixture'
import OperacoesView from './OperacoesView.vue'
vi.mock('../services/auditoria.api', () => ({
  auditoriaApi: {
    listarEventos: vi.fn<typeof auditoriaApi.listarEventos>(),
    consultarFiltros: vi.fn<typeof auditoriaApi.consultarFiltros>(),
  },
}))
const schema = JSON.parse(
  readFileSync(
    resolve(
      dirname(fileURLToPath(import.meta.url)),
      '../../../../../contracts/observability/log.schema.json',
    ),
    'utf8',
  ),
)
const opcoes = {
  usuarios: ['gestor.outro', 'rh.outro'],
  meses: ['2026-10', '2026-11'],
  lojas: ['13', '21'],
  marcas: ['10', '20'],
  cargos: ['100', '300'],
}
const simulacaoComFalha = eventoExemplo({
  instante: '2026-11-04T15:30:00Z',
  usuario_login: 'gestor.outro',
  job: { id: 'job-2', nome: null, status: 'erro' },
  origem_id: 'resultado-2',
  loja: '21',
  marca: '20',
  cargo: '300',
  status: 'erro_codigo',
  veredito: 'indeterminado',
})
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-17T12:00:00Z'))
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
  vi.mocked(auditoriaApi.consultarFiltros).mockResolvedValue(opcoes)
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(
    paginaEventosExemplo([simulacaoComFalha, eventoExemplo()], {
      contadores: { eventos: 2, usuarios: 2, regras: 2, simulacoes_com_falha: 1 },
    }),
  )
})
afterEach(() => {
  wrapper?.unmount()
  vi.useRealTimers()
  vi.restoreAllMocks()
})
async function abrir(caminho = '/auditoria') {
  const pinia = createPinia()
  usarStoreSessao(pinia).papel = 'auditor'
  usarStoreSessao(pinia).login = 'auditor.teste'
  const vazio = { render: () => null }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/auditoria', name: 'auditoria-operacoes', component: OperacoesView },
      { path: '/auditoria/dossies', component: vazio },
      { path: '/auditoria/dossies/:id', name: 'auditoria-dossie', component: vazio },
    ],
  })
  await router.push(caminho)
  await router.isReady()
  wrapper = mount(OperacoesView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return router
}
function botao(texto: string) {
  return wrapper!.findAll('button').find((item) => item.text().includes(texto))!
}
function ultimaConsulta() {
  return vi.mocked(auditoriaApi.listarEventos).mock.lastCall
}
function logs(nivel: 'info' | 'error') {
  return vi.mocked(console[nivel]).mock.calls.map(([linha]) => JSON.parse(String(linha)))
}
it('mostra os eventos de todos os usuários no mês corrente, com contadores e códigos', async () => {
  await abrir()
  expect(ultimaConsulta()).toEqual([{ mes: '2026-11' }, 0, 12, expect.any(AbortSignal)])
  const texto = wrapper!.text()
  for (const esperado of [
    'auditor.teste',
    'rh.outro',
    'gestor.outro',
    'Simulação',
    'Erro no código · Indeterminado',
    'Sucesso · Viável',
    'Comissão de novembro',
    'Regra sem nome',
    'job-2',
    'Usuários com atividade',
    'Regras rastreadas',
    'Simulações com falha',
    '2 eventos',
  ])
    expect(texto).toContain(esperado)
  for (const rotulo of ['LOJA-13', 'PRETO', 'VENDEDOR LOJA']) expect(texto).not.toContain(rotulo)
  const linhas = wrapper!
    .findAll('tbody tr')
    .map((linha) => linha.findAll('td').map((celula) => celula.text()))
  expect(linhas[0]!.slice(0, 8)).toEqual([
    '04/11/202612:30:00',
    'gestor.outro',
    'SimulaçãoErro no código · Indeterminado',
    'Regra sem nomejob-2',
    '21',
    '20',
    '300',
    'erro',
  ])
  expect(linhas[1]!.slice(4, 7)).toEqual(['13', '10', '100'])
  expect(wrapper!.get('[aria-current="page"]').text()).toBe('Todas as operações')
  const contadores = wrapper!.findAll('dd').map((item) => item.text())
  expect(contadores).toEqual(['2', '2', '2', '1'])
  expect(wrapper!.get<HTMLSelectElement>('select[name="mes"]').element.value).toBe('2026-11')
  expect(wrapper!.get('select[name="mes"]').text()).toContain('10/2026')
})
it('aplicar um filtro muda o endereço, a lista e os contadores', async () => {
  const router = await abrir()
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(
    paginaEventosExemplo([simulacaoComFalha], {
      contadores: { eventos: 1, usuarios: 1, regras: 1, simulacoes_com_falha: 1 },
    }),
  )
  await wrapper!.get('select[name="usuario"]').setValue('gestor.outro')
  await wrapper!.get('input[name="regra"]').setValue(' Bônus ')
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(router.currentRoute.value.query).toEqual({
    usuario: 'gestor.outro',
    mes: '2026-11',
    regra: 'Bônus',
  })
  expect(ultimaConsulta()).toEqual([
    { usuario: 'gestor.outro', mes: '2026-11', regra: 'Bônus' },
    0,
    12,
    expect.any(AbortSignal),
  ])
  expect(wrapper!.findAll('dd').map((item) => item.text())).toEqual(['1', '1', '1', '1'])
  expect(wrapper!.text()).not.toContain('Comissão de novembro')
})
it('limpar filtros volta ao mês corrente, sem os outros filtros', async () => {
  const router = await abrir('/auditoria?usuario=rh.outro&mes=2026-10&loja=13&pagina=1')
  expect(ultimaConsulta()).toEqual([
    { usuario: 'rh.outro', mes: '2026-10', loja: '13' },
    1,
    12,
    expect.any(AbortSignal),
  ])
  expect(wrapper!.get<HTMLSelectElement>('select[name="usuario"]').element.value).toBe('rh.outro')
  await botao('Limpar filtros').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query).toEqual({})
  expect(ultimaConsulta()).toEqual([{ mes: '2026-11' }, 0, 12, expect.any(AbortSignal)])
  expect(wrapper!.get<HTMLSelectElement>('select[name="usuario"]').element.value).toBe('')
  expect(wrapper!.get<HTMLSelectElement>('select[name="loja"]').element.value).toBe('')
  expect(wrapper!.get<HTMLSelectElement>('select[name="mes"]').element.value).toBe('2026-11')
})
it('todos os meses fica no endereço e não filtra o mês', async () => {
  const router = await abrir()
  await wrapper!.get('select[name="mes"]').setValue('todos')
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(router.currentRoute.value.query).toEqual({ mes: 'todos' })
  expect(ultimaConsulta()).toEqual([{}, 0, 12, expect.any(AbortSignal)])
})
it('mantém selecionável o valor do endereço que não está nas opções', async () => {
  await abrir('/auditoria?usuario=antigo.usuario&mes=2025-01')
  expect(wrapper!.get<HTMLSelectElement>('select[name="usuario"]').element.value).toBe(
    'antigo.usuario',
  )
  expect(wrapper!.get<HTMLSelectElement>('select[name="mes"]').element.value).toBe('2025-01')
})
it('aplicar de novo os mesmos filtros consulta de novo', async () => {
  await abrir('/auditoria?mes=2026-11')
  expect(auditoriaApi.listarEventos).toHaveBeenCalledTimes(1)
  await wrapper!.get('form').trigger('submit')
  await flushPromises()
  expect(auditoriaApi.listarEventos).toHaveBeenCalledTimes(2)
})
it('pagina de 12 em 12 pelo endereço', async () => {
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(
    paginaEventosExemplo([eventoExemplo()], { total: 30 }),
  )
  const router = await abrir('/auditoria?usuario=rh.outro')
  expect(botao('Anterior').attributes('disabled')).toBeDefined()
  expect(wrapper!.text()).toContain('1–1 de 30 eventos · 12 por página')
  expect(
    wrapper!.findAll('nav[aria-label="Paginação dos eventos"] button').map((b) => b.text()),
  ).toEqual(['← Anterior', '1', '2', '3', 'Próxima →'])
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(
    paginaEventosExemplo([eventoExemplo()], { total: 30, pagina: 1 }),
  )
  await botao('Próxima').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query).toEqual({
    usuario: 'rh.outro',
    mes: '2026-11',
    pagina: '1',
  })
  expect(ultimaConsulta()).toEqual([
    { usuario: 'rh.outro', mes: '2026-11' },
    1,
    12,
    expect.any(AbortSignal),
  ])
  expect(wrapper!.text()).toContain('13–13 de 30 eventos · 12 por página')
  await wrapper!.get('button[aria-label="Página 3"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.query.pagina).toBe('2')
  expect(ultimaConsulta()?.[1]).toBe(2)
})
it('consultar abre o dossiê na aba do evento, e voltar mantém os filtros', async () => {
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(
    paginaEventosExemplo([
      eventoExemplo(),
      eventoExemplo({ tipo: 'versao_regra', origem_id: 'regra-1', versao: 1 }),
      eventoExemplo({ tipo: 'entrada', origem_id: 'entrada-1', finalidade: 'entrada_inicial' }),
    ]),
  )
  const router = await abrir('/auditoria?usuario=rh.outro&mes=2026-10')
  const links = wrapper!.findAll('a').filter((item) => item.text() === 'Consultar →')
  expect(links.map((item) => item.attributes('href'))).toEqual([
    '/auditoria/dossies/job-1?aba=simulacoes',
    '/auditoria/dossies/job-1?aba=regra',
    '/auditoria/dossies/job-1?aba=conversa',
  ])
  await links[0]!.trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.fullPath).toBe('/auditoria/dossies/job-1?aba=simulacoes')
  expect(auditoriaApi.listarEventos).toHaveBeenCalledTimes(1)
  router.back()
  await flushPromises()
  expect(router.currentRoute.value.query).toEqual({ usuario: 'rh.outro', mes: '2026-10' })
  expect(ultimaConsulta()).toEqual([
    { usuario: 'rh.outro', mes: '2026-10' },
    0,
    12,
    expect.any(AbortSignal),
  ])
  expect(wrapper!.get<HTMLSelectElement>('select[name="usuario"]').element.value).toBe('rh.outro')
})
it('mostra a lista vazia com os contadores', async () => {
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(
    paginaEventosExemplo([], {
      contadores: { eventos: 0, usuarios: 0, regras: 0, simulacoes_com_falha: 0 },
    }),
  )
  await abrir()
  expect(wrapper!.text()).toContain('Nenhum evento encontrado com estes filtros.')
  expect(wrapper!.find('table').exists()).toBe(false)
})
it('mostra carregamento enquanto a consulta está pendente', async () => {
  vi.mocked(auditoriaApi.listarEventos).mockImplementation(() => new Promise(() => undefined))
  await abrir()
  expect(wrapper!.get('[role="status"]').text()).toContain('Carregando operações')
})
it('exibe como texto o nome da regra', async () => {
  vi.mocked(auditoriaApi.listarEventos).mockResolvedValue(
    paginaEventosExemplo([
      eventoExemplo({
        job: { id: 'job-1', nome: '<img src=x onerror=alert(1)>', status: 'liberado' },
      }),
    ]),
  )
  await abrir()
  expect(wrapper!.text()).toContain('<img src=x onerror=alert(1)>')
  expect(wrapper!.find('img[src="x"]').exists()).toBe(false)
})
it.each([
  ['sem_permissao', 'Acesso negado'],
  ['requisicao_invalida', 'Revise-os'],
] as const)(
  'mapeia %s e registra a falha sem o texto do filtro de regra',
  async (code, mensagem) => {
    vi.mocked(auditoriaApi.listarEventos).mockRejectedValue(
      new HttpError(403, 'segredo-interno', { code }),
    )
    await abrir('/auditoria?regra=Comissão confidencial')
    expect(wrapper!.get('[role="alert"]').text()).toContain(mensagem)
    expect(wrapper!.text()).not.toContain('segredo-interno')
    const falhas = logs('error')
    expect(falhas).toHaveLength(1)
    const linha = falhas[0]
    for (const campo of schema.required) expect(linha).toHaveProperty(campo)
    expect(schema.properties.level.enum).toContain(linha.level)
    expect(linha).toMatchObject({
      level: 'ERROR',
      'service.name': 'synapse-frontend',
      extra: { operacao: 'listar_eventos_auditoria', resultado: 'falha', codigo: code },
    })
    expect(linha).not.toHaveProperty('job_id')
    expect(JSON.stringify(linha)).not.toMatch(/confidencial|segredo-interno/)
  },
)
it('registra a falha das opções e mantém a lista', async () => {
  vi.mocked(auditoriaApi.consultarFiltros).mockRejectedValueOnce(new Error('segredo-interno'))
  await abrir()
  expect(wrapper!.get('[role="alert"]').text()).toContain(
    'Não foi possível carregar as opções dos filtros',
  )
  expect(wrapper!.text()).toContain('Comissão de novembro')
  expect(logs('error')).toEqual([
    expect.objectContaining({
      extra: expect.objectContaining({
        operacao: 'consultar_filtros_auditoria',
        resultado: 'falha',
        codigo: 'indisponivel',
      }),
    }),
  ])
  await botao('Tentar novamente').trigger('click')
  await flushPromises()
  expect(auditoriaApi.consultarFiltros).toHaveBeenCalledTimes(2)
  expect(wrapper!.find('[role="alert"]').exists()).toBe(false)
  expect(wrapper!.get('select[name="usuario"]').text()).toContain('gestor.outro')
})
