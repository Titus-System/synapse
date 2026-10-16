import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/jobs/:id/correcao',
    alias: '/correcao',
    name: 'correcao-regra',
    component: () => import('./views/CorrecaoRegraView.vue'),
    meta: { layout: 'blank' },
  },
] satisfies RouteRecordRaw[]
