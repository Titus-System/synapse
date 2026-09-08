import 'vue-router'
import type { LayoutName } from '@/layouts/registry'

declare module 'vue-router' {
  interface RouteMeta {
    /** Layout wrapping the view. Absent = 'default'. */
    layout?: LayoutName
    /** Label in the sidebar menu. Absent = the route doesn't appear in the menu. */
    navLabel?: string
    /** Position in the menu (lower first). */
    navOrder?: number
  }
}
