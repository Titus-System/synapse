<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import ExampleCard from '../components/ExampleCard.vue'
import { useExampleFilter } from '../composables/useExampleFilter'
import { useExampleStore } from '../stores/example'

const router = useRouter()

const store = useExampleStore()
const { items, loading, error } = storeToRefs(store)

const { term, filtered } = useExampleFilter(items)

onMounted(() => store.fetchAll())

function openDetail(id: string) {
  router.push({ name: 'example-detail', params: { id } })
}
</script>

<template>
  <section class="mx-auto max-w-3xl">
    <h1 class="text-2xl font-semibold text-gray-900">Example feature</h1>
    <p class="mt-1 text-gray-600">
      Reference template. Copy this folder's structure when creating a real feature, then delete
      this one.
    </p>

    <input
      v-model="term"
      type="search"
      placeholder="Filter…"
      class="mt-6 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 focus:border-blue-500 focus:outline-none"
    />

    <p v-if="loading" class="mt-6 text-gray-500">Loading…</p>

    <p v-else-if="error" class="mt-6 rounded-lg bg-red-50 p-4 text-red-700">{{ error }}</p>

    <p v-else-if="filtered.length === 0" class="mt-6 text-gray-500">No items.</p>

    <div v-else class="mt-6 grid gap-3">
      <ExampleCard v-for="item in filtered" :key="item.id" :item="item" @select="openDetail" />
    </div>
  </section>
</template>
