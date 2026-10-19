<script setup lang="ts">
defineProps<{ lojas: string[]; competencias: string[] }>()
const matricula = defineModel<string>('matricula', { required: true })
const loja = defineModel<string>('loja', { required: true })
const competencia = defineModel<string>('competencia', { required: true })
defineEmits<{ limpar: [] }>()
</script>

<template>
  <fieldset class="mb-5 rounded-lg border border-[#FFDBCD] p-4">
    <legend class="px-2 font-bold">Filtrar detalhamento</legend>
    <div class="grid gap-3 sm:grid-cols-3">
      <label class="flex min-w-0 flex-col gap-1 text-sm">
        Matrícula
        <input
          v-model="matricula"
          type="search"
          autocomplete="off"
          placeholder="Digite parte da matrícula"
          class="w-full rounded-lg border border-[#DFC0B2] bg-white px-3 py-2"
        />
      </label>
      <label class="flex min-w-0 flex-col gap-1 text-sm">
        Loja
        <select v-model="loja" aria-label="Loja" class="w-full rounded-lg border border-[#DFC0B2] bg-white px-3 py-2">
          <option value="">Todas as lojas</option>
          <option v-for="opcao in lojas" :key="opcao" :value="opcao">{{ opcao }}</option>
        </select>
      </label>
      <label class="flex min-w-0 flex-col gap-1 text-sm">
        Competência
        <select
          v-model="competencia"
          aria-label="Competência"
          class="w-full rounded-lg border border-[#DFC0B2] bg-white px-3 py-2"
        >
          <option value="">Todas as competências</option>
          <option v-for="opcao in competencias" :key="opcao" :value="opcao">
            {{ opcao.split('-').reverse().join('/') }}
          </option>
        </select>
      </label>
    </div>
    <button
      type="button"
      class="mt-3 cursor-pointer text-sm text-[#9D4400] underline"
      @click="$emit('limpar')"
    >
      Limpar filtros
    </button>
  </fieldset>
</template>
