import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    // The feature that "owns" the home page declares '/'. When this example
    // feature is removed, another one takes over that path.
    path: '/',
    name: 'example-list',
    component: () => import('./views/ExampleListView.vue'),
    meta: { navLabel: 'Example', navOrder: 10 },
  },
  {
    path: '/example/:id',
    name: 'example-detail',
    component: () => import('./views/ExampleDetailView.vue'),
  },
] satisfies RouteRecordRaw[]
