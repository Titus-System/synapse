import type { RouteRecordRaw } from 'vue-router'
import { usarStoreSessao } from '@/stores/session'
export function exigirAuditor() {
  return usarStoreSessao().papel === 'auditor' ? true : '/'
}
export default [
  {
    path: '/auditoria/dossies',
    name: 'auditoria-dossies',
    component: () => import('./views/DossiesView.vue'),
    meta: { layout: 'blank' },
    beforeEnter: exigirAuditor,
  },
  {
    path: '/auditoria/dossies/:id',
    name: 'auditoria-dossie',
    component: () => import('./views/DossieView.vue'),
    meta: { layout: 'blank' },
    beforeEnter: exigirAuditor,
  },
] satisfies RouteRecordRaw[]
