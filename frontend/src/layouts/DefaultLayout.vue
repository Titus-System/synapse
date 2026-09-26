<script setup lang="ts">
import TheSidebar from '@/components/TheSidebar.vue'
</script>

<template>
  <div class="min-h-[100dvh] bg-[#FFF8F6] lg:grid lg:h-[100dvh] lg:grid-cols-[16rem_minmax(0,1fr)] lg:overflow-hidden">
    <TheSidebar class="hidden lg:flex" />
    <main class="min-w-0 overflow-x-hidden p-4 sm:p-6 lg:min-h-0 lg:overflow-y-auto lg:p-8">
      <slot />
    </main>
  </div>
</template>
