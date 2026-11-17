import { usarStoreSessao } from '@/stores/session'
import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/',
    name: 'bootstrap',
    component: () => import('./views/BootstrapView.vue'),
    // Um redirect seria resolvido antes da guarda de login, ainda sem o papel na
    // sessão, e o login voltaria para a nova regra em vez de voltar para a raiz.
    beforeEnter: () =>
      usarStoreSessao().papel === 'auditor' ? '/auditoria' : '/nova-regra',
  },
] satisfies RouteRecordRaw[]
