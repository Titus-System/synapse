<script setup lang="ts">
import TheSidebar from '@/components/TheSidebar.vue'
</script>

<template>
  <div class="min-h-screen bg-gray-50 md:grid md:grid-cols-[240px_1fr]">
    <TheSidebar />
    <main class="overflow-x-auto p-8">
      <slot />
    </main>
  </div>
</template>
