<script setup lang="ts">
import { computed } from 'vue'
import type { ContadoresEventosAuditoria } from '../types'
const props = defineProps<{ contadores: ContadoresEventosAuditoria }>()
const itens = computed(() => [
  { nome: 'Eventos', valor: props.contadores.eventos },
  { nome: 'Usuários com atividade', valor: props.contadores.usuarios },
  { nome: 'Regras rastreadas', valor: props.contadores.regras },
  { nome: 'Simulações com falha', valor: props.contadores.simulacoes_com_falha },
])
</script>
<template>
  <dl class="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
    <div
      v-for="item in itens"
      :key="item.nome"
      class="rounded-2xl border border-[#dec0b1] bg-white p-6 shadow-sm"
    >
      <dt class="text-sm text-[#806b5d]">{{ item.nome }}</dt>
      <dd class="mt-3 font-serif text-4xl font-bold text-[#2e1a10]">
        {{ item.valor.toLocaleString('pt-BR') }}
      </dd>
    </div>
  </dl>
</template>
