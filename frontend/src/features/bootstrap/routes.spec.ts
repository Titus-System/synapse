import { beforeEach, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { usarStoreSessao } from '@/stores/session'
import routes from './routes'
beforeEach(() => setActivePinia(createPinia()))
it.each([
  ['auditor', '/auditoria/dossies'],
  ['profissional-rh', '/nova-regra'],
  [undefined, '/nova-regra'],
] as const)('direciona %s para %s', async (papel, destino) => {
  usarStoreSessao().papel = papel
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      ...routes,
      { path: '/auditoria/dossies', component: { template: '<div />' } },
      { path: '/nova-regra', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  expect(router.currentRoute.value.path).toBe(destino)
})
