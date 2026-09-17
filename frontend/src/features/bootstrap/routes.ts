import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/',
    name: 'bootstrap',
    component: () => import('./views/BootstrapView.vue'),
    meta: { layout: 'blank' },
  },
] satisfies RouteRecordRaw[]
