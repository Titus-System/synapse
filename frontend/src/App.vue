<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import { layouts } from '@/layouts/registry'

const route = useRoute()

// Each route picks its layout via `meta.layout`; without it, falls back to 'default'.
const layout = computed(() => layouts[route.meta.layout ?? 'default'])
</script>

<template>
  <component :is="layout">
    <RouterView />
  </component>
</template>
