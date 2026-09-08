<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary'
    disabled?: boolean
    type?: 'button' | 'submit'
  }>(),
  { variant: 'primary', disabled: false, type: 'button' },
)

// Full classes as literals — Tailwind scans the template and script text,
// so an interpolated string (`bg-${color}-500`) isn't detected.
const variantClasses: Record<'primary' | 'secondary', string> = {
  primary: 'bg-blue-600 text-white hover:bg-blue-700',
  secondary: 'border border-gray-300 bg-white text-gray-800 hover:bg-gray-50',
}

const classes = computed(() => variantClasses[props.variant])
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    class="cursor-pointer rounded-lg px-4 py-2 font-medium disabled:cursor-not-allowed disabled:opacity-50"
    :class="classes"
  >
    <slot />
  </button>
</template>
