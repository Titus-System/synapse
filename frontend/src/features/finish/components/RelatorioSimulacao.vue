<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { RepresentacaoRegra, ResultadoLinhas } from '@/types/api'
import {
  formatarReais,
  organizarLinhas,
  rotulosContribuicoes,
} from '../composables/apresentacaoDetalhamento'

const props = defineProps<{
  aberto: boolean
  carregando: boolean
  erro: string | null
  linhas?: ResultadoLinhas
  regra?: RepresentacaoRegra
}>()
defineEmits<{ alternar: []; tentarNovamente: [] }>()
const pagina = ref(0)
const linhasOrdenadas = computed(() => organizarLinhas(props.linhas ?? {}))
const visiveis = computed(() =>
  linhasOrdenadas.value.slice(pagina.value * 25, (pagina.value + 1) * 25),
)
const rotulos = computed(() => rotulosContribuicoes(props.regra))
watch(
  () => props.linhas,
  () => {
    pagina.value = 0
  },
)

function competencia(valor: string) {
  const [ano, mes] = valor.split('-')
  return `${mes}/${ano}`
}
</script>

<template>
  <section class="mx-4 mb-8 min-w-0 text-[#584237] sm:mx-8" aria-label="Relatório da simulação">
    <button
      type="button"
      class="flex cursor-pointer items-center gap-2 text-sm text-[#9D4400] hover:underline focus-visible:outline-2 focus-visible:outline-offset-4"
      :aria-expanded="aberto"
      aria-controls="relatorio-simulacao"
      @click="$emit('alternar')"
    >
      {{ aberto ? 'Fechar relatório' : 'Abrir relatório' }}
      <span aria-hidden="true">{{ aberto ? '⌃' : '⌄' }}</span>
    </button>
    <div v-if="aberto" id="relatorio-simulacao" class="mt-4" :aria-busy="carregando">
      <p v-if="carregando" role="status" class="py-6">Carregando relatório...</p>
      <div
        v-else-if="erro"
        role="alert"
        class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-4"
      >
        <p>{{ erro }}</p>
        <button
          type="button"
          class="mt-3 cursor-pointer text-[#9D4400] underline"
          @click="$emit('tentarNovamente')"
        >
          Tentar novamente
        </button>
      </div>
      <p
        v-else-if="!linhas || !linhasOrdenadas.length"
        role="status"
        class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-4"
      >
        O detalhamento não está disponível para esta simulação.
      </p>
      <template v-else>
        <p class="mb-3 text-sm">Comissões por competência e colaborador.</p>
        <div
          class="max-h-[32rem] overflow-auto rounded-lg focus-visible:outline-2"
          tabindex="0"
          role="region"
          aria-label="Comissões por colaborador"
        >
          <table
            class="w-full min-w-[66rem] border-separate border-spacing-x-2 border-spacing-y-3 text-left text-sm"
          >
            <caption class="sr-only">
              Detalhamento das comissões da simulação
            </caption>
            <thead class="sticky top-0 z-10 bg-white text-[#2e1a10]">
              <tr>
                <th scope="col">Competência</th>
                <th scope="col">Marca</th>
                <th scope="col">Loja</th>
                <th scope="col">Matrícula</th>
                <th scope="col">Cargo</th>
                <th scope="col">Comissão atual</th>
                <th scope="col">Comissão simulada</th>
                <th scope="col">Diferença</th>
                <th scope="col">Contribuições da regra</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="linha in visiveis" :key="`${linha.competencia}/${linha.matricula}`">
                <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                  {{ competencia(linha.competencia) }}
                </td>
                <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                  {{ linha.cod_marca }}
                </td>
                <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                  {{ linha.cod_loja }}
                </td>
                <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                  {{ linha.matricula }}
                </td>
                <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                  {{ linha.cod_cargo }}
                </td>
                <td
                  class="whitespace-nowrap rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2"
                >
                  {{ formatarReais(linha.comissao_baseline) }}
                </td>
                <td
                  class="whitespace-nowrap rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2"
                >
                  {{ formatarReais(linha.comissao_simulada) }}
                </td>
                <td
                  class="whitespace-nowrap rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2"
                >
                  {{ formatarReais(linha.diferenca) }}
                </td>
                <td class="min-w-64 rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                  <ul v-if="Object.keys(linha.contribuicoes).length" class="space-y-1">
                    <li v-for="(valor, referencia) in linha.contribuicoes" :key="referencia">
                      {{ rotulos[referencia] ?? 'Condição adicional da regra' }}:
                      {{ formatarReais(valor) }}
                    </li>
                  </ul>
                  <span v-else>Sem alteração</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
          <p role="status">Página {{ pagina + 1 }} · {{ linhasOrdenadas.length }} registros</p>
          <nav aria-label="Páginas do relatório" class="flex gap-3">
            <button
              type="button"
              :disabled="pagina === 0"
              class="cursor-pointer rounded-lg border border-[#DFC0B2] px-4 py-2 text-[#9D4400] disabled:cursor-default disabled:opacity-50"
              @click="pagina -= 1"
            >
              Anterior
            </button>
            <button
              type="button"
              :disabled="(pagina + 1) * 25 >= linhasOrdenadas.length"
              class="cursor-pointer rounded-lg border border-[#DFC0B2] px-4 py-2 text-[#9D4400] disabled:cursor-default disabled:opacity-50"
              @click="pagina += 1"
            >
              Próxima
            </button>
          </nav>
        </div>
      </template>
    </div>
  </section>
</template>
