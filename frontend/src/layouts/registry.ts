import type { Component } from 'vue'
import DefaultLayout from './DefaultLayout.vue'
import BlankLayout from './BlankLayout.vue'

export const layouts = {
  default: DefaultLayout,
  blank: BlankLayout,
} satisfies Record<string, Component>

export type LayoutName = keyof typeof layouts
