<script setup lang="ts">
import {
  filtrosIniciais,
  formatarCompetencia,
  type FiltrosDoHistorico,
} from '../composables/filtrosDoHistorico'

defineProps<{ competencias: string[] }>()
const filtros = defineModel<FiltrosDoHistorico>('filtros', { required: true })

function atualizarData(campo: 'criadaDesde' | 'criadaAte', valor: string) {
  filtros.value = { ...filtros.value, [campo]: valor }
}

function alternarCompetencia(competencia: string) {
  const selecionadas = filtros.value.competencias
  filtros.value = {
    ...filtros.value,
    competencias: selecionadas.includes(competencia)
      ? selecionadas.filter((atual) => atual !== competencia)
      : [...selecionadas, competencia],
  }
}

function limpar() {
  filtros.value = { ...filtrosIniciais(), ordenacao: filtros.value.ordenacao }
}
</script>

<template>
  <section
    class="mb-7 rounded-2xl bg-white px-6 py-6 text-sm text-[#644b3e] shadow-sm sm:px-8"
    aria-label="Filtros avançados"
  >
    <div class="grid gap-6 md:grid-cols-[auto_auto_minmax(0,1fr)]">
      <label class="flex flex-col gap-2">
        Criada a partir de
        <input
          type="date"
          class="h-11 rounded-xl border border-[#ead8cd] px-3 text-[#2e1a10]"
          :value="filtros.criadaDesde"
          :max="filtros.criadaAte || undefined"
          @input="atualizarData('criadaDesde', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <label class="flex flex-col gap-2">
        Criada até
        <input
          type="date"
          class="h-11 rounded-xl border border-[#ead8cd] px-3 text-[#2e1a10]"
          :value="filtros.criadaAte"
          :min="filtros.criadaDesde || undefined"
          @input="atualizarData('criadaAte', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <fieldset class="min-w-0">
        <legend class="mb-2">Meses simulados</legend>
        <p v-if="competencias.length === 0" class="text-[#9c8272]">Nenhum mês disponível.</p>
        <div v-else class="flex flex-wrap gap-2">
          <label
            v-for="competencia in competencias"
            :key="competencia"
            class="flex cursor-pointer items-center gap-2 rounded-full border px-3 py-2"
            :class="
              filtros.competencias.includes(competencia)
                ? 'border-[#f87519] bg-[#fff0e9] text-[#2e1a10]'
                : 'border-[#ead8cd] hover:bg-[#fff8f5]'
            "
          >
            <input
              type="checkbox"
              class="accent-[#f87519]"
              :checked="filtros.competencias.includes(competencia)"
              @change="alternarCompetencia(competencia)"
            />
            {{ formatarCompetencia(competencia) }}
          </label>
        </div>
      </fieldset>
    </div>
    <div class="mt-6 flex justify-end">
      <button
        type="button"
        class="cursor-pointer rounded-lg px-4 py-2 font-medium text-[#a74700] hover:bg-[#fff0e9]"
        @click="limpar"
      >
        Limpar filtros
      </button>
    </div>
  </section>
</template>
