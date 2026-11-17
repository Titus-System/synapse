import { beforeEach, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { usarStoreSessao } from '@/stores/session'
import routes, { exigirAuditor } from './routes'
beforeEach(() => setActivePinia(createPinia()))
it('isola as rotas do painel e dos dossiês do layout operacional', () => {
  expect(routes.map((rota) => rota.path)).toEqual([
    '/auditoria',
    '/auditoria/dossies',
    '/auditoria/dossies/:id',
  ])
  for (const rota of routes) {
    expect(rota.meta.layout).toBe('blank')
    expect(rota.beforeEnter).toBe(exigirAuditor)
  }
})
it.each(['profissional-rh', undefined] as const)('redireciona %s', (papel) => {
  usarStoreSessao().papel = papel
  expect(exigirAuditor()).toBe('/')
})
it('permite auditor', () => {
  usarStoreSessao().papel = 'auditor'
  expect(exigirAuditor()).toBe(true)
})
