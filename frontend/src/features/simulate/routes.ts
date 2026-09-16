import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/simulacao',
    name: 'simulacao',
    component: () => import('./views/SimulateView.vue'),
    meta: { layout: 'default' },
  },
] satisfies RouteRecordRaw[]