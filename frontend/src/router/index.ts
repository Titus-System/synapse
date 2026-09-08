import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { config } from '@/config/env'

const modules = import.meta.glob<{ default: RouteRecordRaw[] }>('../features/*/routes.ts', {
  eager: true,
})

// Deterministic order: Vite returns the glob keys sorted by path.
const featureRoutes = Object.values(modules).flatMap((module) => module.default)

const router = createRouter({
  history: createWebHistory(config.baseUrl),
  routes: [
    ...featureRoutes,
    // The catch-all stays explicit and last — the glob doesn't guarantee
    // that a feature route won't come after it.
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/NotFoundView.vue'),
    },
  ],
})

export default router
