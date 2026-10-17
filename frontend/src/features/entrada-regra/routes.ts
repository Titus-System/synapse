import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/nova-regra',
    alias: '/entrada-regra',
    name: 'nova-regra',
    component: () => import('./views/EntradaRegraView.vue'),
    meta: { navLabel: 'Nova regra', navOrder: 10, layout: 'blank' },
  },
] satisfies RouteRecordRaw[]
