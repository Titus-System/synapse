<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

const router = useRouter()

const links = computed(() =>
  router
    .getRoutes()
    .filter((route) => route.meta.navLabel !== undefined)
    .sort((a, b) => (a.meta.navOrder ?? 0) - (b.meta.navOrder ?? 0)),
)
</script>

<template>
  <nav class="border-b border-gray-200 bg-white px-4 py-6 md:border-r md:border-b-0">
    <p class="mb-6 text-xs font-semibold tracking-widest text-gray-500 uppercase">App</p>
    <ul class="flex flex-col gap-1">
      <li v-for="link in links" :key="link.path">
        <RouterLink
          :to="link.path"
          class="block rounded-lg px-3 py-2 text-gray-800 hover:bg-gray-100"
          active-class="bg-blue-50 font-semibold text-blue-700"
        >
          {{ link.meta.navLabel }}
        </RouterLink>
      </li>
    </ul>
  </nav>
</template>
