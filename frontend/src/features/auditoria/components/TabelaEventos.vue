<script setup lang="ts">
import {
  abaDoEvento,
  diaAuditoria,
  horaAuditoria,
  seloDoStatus,
  situacaoDoEvento,
  tipoDoEvento,
} from '../composables/apresentacaoAuditoria'
import type { EventoAuditoria } from '../types'
defineProps<{ eventos: EventoAuditoria[] }>()
</script>
<template>
  <div class="overflow-x-auto">
    <table class="w-full text-left text-sm">
      <thead class="bg-[#fff0e9] text-xs font-semibold text-[#2e1a10]">
        <tr>
          <th class="px-5 py-4">Data e hora ↓</th>
          <th class="px-5 py-4">Usuário</th>
          <th class="px-5 py-4">Evento</th>
          <th class="px-5 py-4">Regra</th>
          <th class="px-5 py-4">Loja</th>
          <th class="px-5 py-4">Marca</th>
          <th class="px-5 py-4">Cargo</th>
          <th class="px-5 py-4">Status atual</th>
          <th class="px-5 py-4">Detalhe</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="evento in eventos"
          :key="`${evento.tipo}:${evento.origem_id}:${evento.instante}`"
          class="border-t border-[#f1ded3] transition hover:bg-[#fff8f5]"
        >
          <td class="whitespace-nowrap px-5 py-5">
            <span class="block text-[#2e1a10]">{{ diaAuditoria(evento.instante) }}</span
            ><span class="mt-1 block text-xs text-[#806b5d]">{{
              horaAuditoria(evento.instante)
            }}</span>
          </td>
          <td class="break-all px-5 py-5 text-[#2e1a10]">{{ evento.usuario_login }}</td>
          <td class="px-5 py-5">
            <span class="block text-[#2e1a10]">{{ tipoDoEvento(evento.tipo) }}</span
            ><span class="mt-1 block text-xs text-[#806b5d]">{{ situacaoDoEvento(evento) }}</span>
          </td>
          <td class="max-w-72 px-5 py-5">
            <span class="block break-words font-semibold text-[#a74700]">{{
              evento.job.nome || 'Regra sem nome'
            }}</span
            ><span class="mt-1 block break-all text-xs text-[#806b5d]">{{ evento.job.id }}</span>
          </td>
          <td class="px-5 py-5 text-[#2e1a10]">{{ evento.loja ?? '—' }}</td>
          <td class="px-5 py-5 text-[#2e1a10]">{{ evento.marca ?? '—' }}</td>
          <td class="px-5 py-5 text-[#2e1a10]">{{ evento.cargo ?? '—' }}</td>
          <td class="px-5 py-5">
            <span
              :class="seloDoStatus(evento.job.status)"
              class="whitespace-nowrap rounded-md px-2.5 py-1 text-xs font-semibold"
              >{{ evento.job.status }}</span
            >
          </td>
          <td class="px-5 py-5">
            <RouterLink
              :to="{
                name: 'auditoria-dossie',
                params: { id: evento.job.id },
                query: { aba: abaDoEvento(evento.tipo) },
              }"
              class="inline-flex min-h-10 items-center whitespace-nowrap rounded-lg px-2 font-semibold text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
              >Consultar →</RouterLink
            >
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
