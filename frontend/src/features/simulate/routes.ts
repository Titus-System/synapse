import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/jobs/:id',
    name: 'simulacao',
    component: () => import('./views/SimulateView.vue'),
    meta: { layout: 'blank' },
  },
] satisfies RouteRecordRaw[]