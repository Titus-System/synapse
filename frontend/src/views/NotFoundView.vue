<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <section class="mx-auto max-w-md text-center">
    <h1 class="text-5xl font-bold text-gray-900">404</h1>
    <p class="mt-2 text-gray-600">Page not found.</p>
    <RouterLink to="/" class="mt-4 inline-block text-blue-600 hover:underline">
      Back to home
    </RouterLink>
  </section>
</template>
