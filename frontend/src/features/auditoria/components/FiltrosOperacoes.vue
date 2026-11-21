<script setup lang="ts">
import { computed } from 'vue'
import { mesAuditoria } from '../composables/apresentacaoAuditoria'
import { TODOS_OS_MESES } from '../composables/filtrosOperacoes'
import type { FiltroPainel, FiltrosEventosAuditoria } from '../types'
const props = defineProps<{ opcoes?: FiltrosEventosAuditoria }>()
const filtro = defineModel<FiltroPainel>({ required: true })
defineEmits<{ aplicar: []; limpar: [] }>()
// O valor que veio do endereço continua selecionado mesmo fora das opções, como o mês corrente
// ainda sem evento ou um usuário que deixou de ter atividade.
function comSelecionado(lista: string[] | undefined, atual: string, todos = '') {
  const opcoes = lista ?? []
  return atual && atual !== todos && !opcoes.includes(atual) ? [atual, ...opcoes] : opcoes
}
const campos = computed(() => [
  {
    campo: 'usuario' as const,
    nome: 'Usuário',
    todos: '',
    textoTodos: 'Todos os usuários',
    opcoes: comSelecionado(props.opcoes?.usuarios, filtro.value.usuario),
    exibir: (valor: string) => valor,
  },
  {
    campo: 'mes' as const,
    nome: 'Mês',
    todos: TODOS_OS_MESES,
    textoTodos: 'Todos os meses',
    opcoes: comSelecionado(props.opcoes?.meses, filtro.value.mes, TODOS_OS_MESES),
    exibir: mesAuditoria,
  },
  {
    campo: 'loja' as const,
    nome: 'Loja',
    todos: '',
    textoTodos: 'Todas as lojas',
    opcoes: comSelecionado(props.opcoes?.lojas, filtro.value.loja),
    exibir: (valor: string) => valor,
  },
  {
    campo: 'marca' as const,
    nome: 'Marca',
    todos: '',
    textoTodos: 'Todas as marcas',
    opcoes: comSelecionado(props.opcoes?.marcas, filtro.value.marca),
    exibir: (valor: string) => valor,
  },
  {
    campo: 'cargo' as const,
    nome: 'Cargo',
    largo: true,
    todos: '',
    textoTodos: 'Todos os cargos',
    opcoes: comSelecionado(props.opcoes?.cargos, filtro.value.cargo),
    exibir: (valor: string) => valor,
  },
])
</script>
<template>
  <form
    aria-labelledby="titulo-filtros-operacoes"
    class="mb-6 rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-6"
    @submit.prevent="$emit('aplicar')"
  >
    <h2 id="titulo-filtros-operacoes" class="mb-5 font-serif text-2xl font-bold text-[#2e1a10]">
      Filtros
    </h2>
    <div class="grid gap-x-4 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
      <label
        v-for="item in campos"
        :key="item.campo"
        :class="'largo' in item ? 'lg:col-span-2' : ''"
        class="block text-sm"
      >
        <span class="mb-2 block font-semibold text-[#2e1a10]">{{ item.nome }}</span>
        <select
          v-model="filtro[item.campo]"
          :name="item.campo"
          class="min-h-11 w-full cursor-pointer rounded-lg border border-[#dec0b1] bg-white px-3 text-[#2e1a10] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
        >
          <option :value="item.todos">{{ item.textoTodos }}</option>
          <option v-for="valor in item.opcoes" :key="valor" :value="valor">
            {{ item.exibir(valor) }}
          </option>
        </select>
      </label>
      <label class="block text-sm sm:col-span-2">
        <span class="mb-2 block font-semibold text-[#2e1a10]">Regra</span>
        <span class="relative block">
          <svg
            class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#806b5d]"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            v-model="filtro.regra"
            name="regra"
            type="search"
            maxlength="200"
            placeholder="Nome ou id da regra"
            class="min-h-11 w-full rounded-lg border border-[#dec0b1] bg-white pl-9 pr-3 text-[#2e1a10] placeholder:text-[#a08a7d] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
          />
        </span>
      </label>
    </div>
    <div class="mt-6 flex flex-wrap justify-end gap-3">
      <button
        type="button"
        class="min-h-11 cursor-pointer rounded-lg border border-[#dec0b1] bg-white px-5 text-sm font-semibold text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
        @click="$emit('limpar')"
      >
        Limpar filtros
      </button>
      <button
        type="submit"
        class="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg bg-[#a74700] px-5 text-sm font-semibold text-white transition hover:bg-[#8a3a00] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
      >
        <svg
          class="size-4"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          aria-hidden="true"
        >
          <path d="M3 5h18l-7 8v6l-4-2v-4L3 5Z" />
        </svg>
        Aplicar filtros
      </button>
    </div>
  </form>
</template>
