import type { RouteRecordRaw } from 'vue-router'

export default [
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
