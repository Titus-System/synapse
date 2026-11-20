import { afterEach, expect, it, vi } from 'vitest'
import { createApp, type App as Aplicacao } from 'vue'
import { createPinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import type { PapelDeNegocio } from '@/services/keycloak'
// O projeto de tipos dos testes só inclui os specs; sem isto, App.vue é checado sem `meta.layout`.
import type {} from '@/types/router'

let aplicacao: Aplicacao | undefined

afterEach(() => {
  aplicacao?.unmount()
  aplicacao = undefined
  vi.restoreAllMocks()
})

// Monta a aplicação na ordem de main.ts, com um roteador novo a cada carga de página.
async function carregarPagina(papel: PapelDeNegocio) {
  window.history.replaceState({}, '', '/')
  vi.resetModules()
  const { http } = await import('@/services/http')
  const get = vi.spyOn(http, 'get').mockReturnValue(new Promise(() => undefined))
  const { usarStoreSessao } = await import('@/stores/session')
  const { default: roteador } = await import('@/router')
  const { default: App } = await import('./App.vue')

  aplicacao = createApp(App)
  const pinia = createPinia()
  aplicacao.use(pinia)
  const sessao = usarStoreSessao(pinia)
  sessao.estaAutenticado = true
  sessao.papel = papel
  aplicacao.use(roteador)
  aplicacao.mount(document.createElement('div'))
  await roteador.isReady()
  await flushPromises()

  return {
    caminho: roteador.currentRoute.value.path,
    consultas: get.mock.calls.map(([caminho]) => caminho),
  }
}

it('carrega a área do auditor sem consultar as regras do RH', async () => {
  const { caminho, consultas } = await carregarPagina('auditor')

  expect(caminho).toBe('/auditoria')
  expect(consultas).toContainEqual(expect.stringMatching(/^\/auditoria\/eventos\?/))
  expect(consultas).toContainEqual('/auditoria/eventos/filtros')
  expect(consultas).not.toContainEqual(expect.stringMatching(/^\/jobs/))
})

it('mantém para o RH a barra lateral, que consulta as regras recentes', async () => {
  const { caminho, consultas } = await carregarPagina('profissional-rh')

  expect(caminho).toBe('/nova-regra')
  expect(consultas).toContainEqual(expect.stringMatching(/^\/jobs\?/))
})
