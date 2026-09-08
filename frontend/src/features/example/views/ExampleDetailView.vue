<script setup lang="ts">
import { ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { HttpError } from '@/services/http'
import { getExample } from '../services/example.api'
import type { ExampleItem } from '../types'

const route = useRoute()

const item = ref<ExampleItem | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

watch(
  () => route.params.id,
  async (id) => {
    if (id === undefined) return

    loading.value = true
    error.value = null
    try {
      item.value = await getExample(String(id))
    } catch (cause) {
      error.value = cause instanceof HttpError ? cause.message : 'Failed to load the item.'
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)
</script>

<template>
  <section class="mx-auto max-w-3xl">
    <RouterLink :to="{ name: 'example-list' }" class="text-sm text-blue-600 hover:underline">
      &larr; Back
    </RouterLink>

    <p v-if="loading" class="mt-6 text-gray-500">Loading…</p>

    <p v-else-if="error" class="mt-6 rounded-lg bg-red-50 p-4 text-red-700">{{ error }}</p>

    <h1 v-else-if="item" class="mt-4 text-2xl font-semibold text-gray-900">{{ item.name }}</h1>
  </section>
</template>
