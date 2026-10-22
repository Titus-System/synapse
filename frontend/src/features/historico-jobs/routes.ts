import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/jobs/:id/historico',
    name: 'historico-do-job',
    component: () => import('./views/HistoricoRegraView.vue'),
    meta: { layout: 'blank' },
  },
  {
    path: '/salvas',
    name: 'regras-salvas',
    component: () => import('./views/HistoricoJobsView.vue'),
    meta: { layout: 'blank' },
  },
  {
    path: '/arquivadas',
    name: 'regras-arquivadas',
    component: () => import('./views/HistoricoJobsView.vue'),
    meta: { layout: 'blank' },
  },
] satisfies RouteRecordRaw[]
