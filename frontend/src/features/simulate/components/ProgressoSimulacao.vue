<script setup lang="ts">
import { computed } from "vue";
import type { EventoEtapa, StatusJob } from "@/types/api";
import { calcularProgresso } from "../composables/progressoSimulacao";

const props = defineProps<{
  status: StatusJob | null;
  etapa: EventoEtapa | null;
  estadoConexao: "conectando" | "aberta" | "reconectando";
}>();

const progresso = computed(() => calcularProgresso(props.status, props.etapa));
</script>

<template>
  <section aria-label="Progresso da simulação" class="mt-6 rounded-lg border-2 border-[#DFC0B2] bg-white/70 p-5">
    <div class="mb-3 flex items-start justify-between gap-4">
      <div>
        <p class="text-xs font-bold uppercase tracking-widest text-[#584237]">Acompanhamento do job</p>
        <h2 class="text-xl font-bold text-[#2B160D]">{{ progresso.titulo }}</h2>
      </div>
      <span class="text-2xl font-bold text-[#F47521]">{{ progresso.percentual }}%</span>
    </div>
    <div class="h-3 overflow-hidden rounded-full bg-[#FFE9E1]" role="progressbar" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="progresso.percentual" :aria-label="progresso.titulo">
      <div class="h-full rounded-full transition-all duration-500 ease-out" :class="progresso.erro ? 'bg-[#950606]' : 'bg-[#F47521]'" :style="{ width: `${progresso.percentual}%` }" />
    </div>
    <p class="mt-3 text-sm text-[#584237]">{{ progresso.detalhe }}</p>
    <p v-if="estadoConexao === 'reconectando'" class="mt-1 text-sm font-bold text-[#B45309]" role="status">Reconectando ao acompanhamento...</p>
    <p v-else-if="estadoConexao === 'conectando'" class="mt-1 text-sm text-[#584237]" role="status">Conectando ao acompanhamento...</p>
  </section>
</template>
