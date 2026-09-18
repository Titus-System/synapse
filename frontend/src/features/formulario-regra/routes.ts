import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/nova-regra',
    name: 'nova-regra',
    component: () => import('./views/FormularioRegraView.vue'),
    meta: { navLabel: 'Nova regra', navOrder: 10, layout: 'blank' },
  },
] satisfies RouteRecordRaw[]
