<script setup lang="ts">
import { nomeDaEntidade } from '@/services/catalogoRh'
import type { FiltrosRelatorio } from '../composables/filtrosRelatorio'
defineProps<{ opcoes: Omit<FiltrosRelatorio, 'matricula'> }>()
const filtros = defineModel<FiltrosRelatorio>({ required: true })
defineEmits<{ aplicar: []; limpar: [] }>()
const dimensoes = [
  { chave: 'loja', titulo: 'Lojas' },
  { chave: 'marca', titulo: 'Marcas' },
  { chave: 'cargo', titulo: 'Cargos' },
  { chave: 'competencia', titulo: 'Competências' },
] as const
</script>
<template>
  <form @submit.prevent="$emit('aplicar')">
    <p class="mb-4 text-sm">
      Selecione os filtros do relatório. Sem seleção, serão exibidos todos os registros dentro do
      escopo da regra.
    </p>
    <div class="grid gap-4 sm:grid-cols-2">
      <fieldset
        v-for="dimensao in dimensoes"
        :key="dimensao.chave"
        class="min-w-0 rounded-lg border border-[#DFC0B2] p-3"
      >
        <legend class="px-1 font-bold">{{ dimensao.titulo }}</legend>
        <div class="max-h-48 space-y-2 overflow-auto">
          <label
            v-for="codigo in opcoes[dimensao.chave]"
            :key="codigo"
            class="flex items-start gap-2 text-sm"
          >
            <input
              v-model="filtros[dimensao.chave]"
              type="checkbox"
              :value="codigo"
              class="mt-1 size-4 shrink-0 accent-[#9D4400]"
            />
            {{
              dimensao.chave === 'competencia'
                ? codigo.split('-').reverse().join('/')
                : nomeDaEntidade(dimensao.chave, codigo)
            }}
          </label>
          <p v-if="!opcoes[dimensao.chave].length" class="text-sm">
            Sem opções no escopo disponível.
          </p>
        </div>
      </fieldset>
    </div>
    <label class="my-4 flex flex-col gap-1 text-sm"
      >Matrícula
      <input
        v-model="filtros.matricula"
        type="search"
        placeholder="Digite parte da matrícula"
        class="rounded-lg border border-[#DFC0B2] px-3 py-2"
      />
    </label>
    <div class="flex flex-wrap gap-3">
      <button type="submit" class="rounded-lg bg-[#9D4400] px-4 py-2 text-white">
        Aplicar filtros
      </button>
      <button
        type="button"
        class="rounded-lg border border-[#DFC0B2] px-4 py-2"
        @click="$emit('limpar')"
      >
        Limpar filtros
      </button>
    </div>
  </form>
</template>
