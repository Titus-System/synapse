<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import { layouts } from '@/layouts/registry'

const route = useRoute()

// Each route picks its layout via `meta.layout`; without it, falls back to 'default'.
const layout = computed(() => layouts[route.meta.layout ?? 'default'])
</script>

<template>
  <!-- Antes da primeira navegação a rota ainda não tem `meta.layout`, e o layout padrão
       montaria a barra lateral do RH, que consulta /jobs, para qualquer papel. -->
  <component :is="layout" v-if="route.matched.length">
    <RouterView />
  </component>
</template>
