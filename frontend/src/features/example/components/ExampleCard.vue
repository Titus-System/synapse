<script setup lang="ts">
import type { ExampleItem } from '../types'

defineProps<{ item: ExampleItem }>()
defineEmits<{ select: [id: string] }>()
</script>

<template>
  <article class="rounded-lg border border-gray-200 bg-white p-4">
    <h2 class="font-medium text-gray-900">{{ item.name }}</h2>
    <button
      type="button"
      class="mt-2 cursor-pointer text-sm text-blue-600 hover:underline"
      @click="$emit('select', item.id)"
    >
      View details
    </button>
  </article>
</template>
