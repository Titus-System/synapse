import { usarStoreSessao } from '@/stores/session'
import type { RouteRecordRaw } from 'vue-router'

export default [
  {
    path: '/',
    name: 'bootstrap',
    redirect: () => (usarStoreSessao().papel === 'auditor' ? '/auditoria/dossies' : '/nova-regra'),
  },
] satisfies RouteRecordRaw[]
