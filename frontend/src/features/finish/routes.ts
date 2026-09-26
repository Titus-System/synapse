import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/jobs/:id/finalizar',
    name: 'finalizar',
    component: () => import('./views/FinishView.vue'),
    meta: { layout: 'blank' },
  },
] satisfies RouteRecordRaw[]