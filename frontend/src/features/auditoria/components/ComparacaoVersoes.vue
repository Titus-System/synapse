<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { campoDaRegra, valorDeAlteracao } from '../composables/apresentacaoAuditoria'
import type { VersaoAuditoria, VersaoResumo } from '../types'
const props = defineProps<{ versoes: VersaoResumo[]; registradas: VersaoAuditoria[] }>()
// Só versões com origem têm o que comparar; a raiz não tem alterações.
const comparaveis = computed(() =>
  [...props.versoes].filter((v) => v.regra_origem_id).sort((a, b) => a.numero - b.numero),
)
const escolhida = ref<string | undefined>(undefined)
watch(
  comparaveis,
  (lista) => {
    if (!lista.some((v) => v.id === escolhida.value)) escolhida.value = lista[lista.length - 1]?.id
  },
  { immediate: true },
)
const atual = computed(() => comparaveis.value.find((v) => v.id === escolhida.value))
const origem = computed(() =>
  props.versoes.find((v) => v.id === atual.value?.regra_origem_id),
)
const origemDe = (id: string) => props.registradas.find((r) => r.id === id)?.origem
function tipo(a: { anterior?: unknown; novo?: unknown }) {
  if (!('anterior' in a) || a.anterior === undefined) return 'Incluída'
  if (!('novo' in a) || a.novo === undefined) return 'Removida'
  return 'Alterada'
}
</script>
<template>
  <section
    class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8"
    aria-label="Comparação de versões"
  >
    <p class="text-xs font-semibold tracking-wide text-[#a74700]">COMPARAÇÃO DE VERSÕES</p>
    <h2 class="mb-4 mt-3 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
      O que mudou<template v-if="atual && origem"> entre v{{ origem.numero }} e v{{ atual.numero }}</template>?
    </h2>
    <p v-if="!comparaveis.length" role="status">Nenhuma versão com origem para comparar.</p>
    <template v-else>
      <label class="mb-5 flex flex-col gap-2 text-sm sm:max-w-sm">
        Versão
        <select v-model="escolhida" class="rounded-lg border border-[#dec0b1] bg-white p-2">
          <option v-for="v in comparaveis" :key="v.id" :value="v.id">
            v{{ v.numero }}<template v-if="origemDe(v.id)"> · {{ origemDe(v.id) }}</template>
          </option>
        </select>
      </label>
      <p v-if="atual && !atual.alteracoes.length" role="status">
        Nenhuma parte alterada em relação à versão de origem.
      </p>
      <div v-else-if="atual" class="overflow-x-auto">
        <table class="w-full min-w-[32rem] text-left text-sm">
          <thead class="bg-[#fff0e9]">
            <tr>
              <th class="p-3">Campo</th>
              <th class="p-3">Antes{{ origem ? ` · v${origem.numero}` : '' }}</th>
              <th class="p-3">Depois · v{{ atual.numero }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="a in atual.alteracoes"
              :key="a.elemento_ref"
              :data-alteracao="a.elemento_ref"
              class="border-t border-[#f1ded3] align-top"
            >
              <td class="break-words p-3 font-semibold" :title="a.elemento_ref">
                {{ campoDaRegra(a.elemento_ref) }}
                <span class="block text-xs font-normal text-[#806b5d]">{{ tipo(a) }}</span>
              </td>
              <td class="break-words p-3">{{ valorDeAlteracao(a.anterior) }}</td>
              <td class="break-words p-3 font-semibold text-[#a74700]">
                {{ valorDeAlteracao(a.novo) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>