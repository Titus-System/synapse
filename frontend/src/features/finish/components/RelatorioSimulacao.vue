<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { RepresentacaoRegra, ResultadoLinhas, ResultadoSimulacao } from '@/types/api'
import FiltrosDetalhamento from './FiltrosDetalhamento.vue'
import TotaisDetalhamento from './TotaisDetalhamento.vue'
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
  decomposicao?: ResultadoSimulacao['decomposicao']
}>()
defineEmits<{ alternar: []; tentarNovamente: [] }>()
const pagina = ref(0)
const matricula = ref('')
const loja = ref('')
const competenciaSelecionada = ref('')
const lojas = computed(() => Object.keys(props.decomposicao?.loja_absoluto ?? {}))
const competencias = computed(() => Object.keys(props.decomposicao?.competencia_absoluto ?? {}))
const linhasOrdenadas = computed(() => organizarLinhas(props.linhas ?? {}))
const linhasFiltradas = computed(() => {
  const trecho = matricula.value.toLocaleLowerCase('pt-BR')
  return linhasOrdenadas.value.filter(
    (linha) =>
      linha.matricula.toLocaleLowerCase('pt-BR').includes(trecho) &&
      (!loja.value || linha.cod_loja === loja.value) &&
      (!competenciaSelecionada.value || linha.competencia === competenciaSelecionada.value),
  )
})
const visiveis = computed(() =>
  linhasFiltradas.value.slice(pagina.value * 25, (pagina.value + 1) * 25),
)
function limparFiltros() {
  matricula.value = ''
  loja.value = ''
  competenciaSelecionada.value = ''
  pagina.value = 0
}
watch(
  [matricula, loja, competenciaSelecionada],
  () => {
    pagina.value = 0
  },
  { flush: 'sync' },
)
const rotulos = computed(() => rotulosContribuicoes(props.regra))
watch(
  () => props.linhas,
  () => {
    limparFiltros()
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
        <FiltrosDetalhamento
          v-model:matricula="matricula"
          v-model:loja="loja"
          v-model:competencia="competenciaSelecionada"
          :lojas="lojas"
          :competencias="competencias"
          @limpar="limparFiltros"
        />
        <TotaisDetalhamento
          :decomposicao="decomposicao"
          :matricula="matricula"
          :loja="loja"
          :competencia="competenciaSelecionada"
        />
        <p
          v-if="!linhasFiltradas.length"
          role="status"
          class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-4"
        >
          Nenhum registro encontrado para os filtros selecionados. Limpe os filtros para ver o
          detalhamento completo.
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
              class="w-full min-w-[73rem] border-separate border-spacing-x-2 border-spacing-y-3 text-left text-sm"
            >
              <caption class="sr-only">
                Detalhamento das comissões da simulação
              </caption>
              <thead class="sticky top-0 z-10 bg-white text-[#2e1a10]">
                <tr>
                  <th
                    scope="col"
                    class="sticky left-2 w-28 min-w-28 bg-white shadow-[0_0_0_0.5rem_white]"
                  >
                    Competência
                  </th>
                  <th
                    scope="col"
                    class="sticky left-32 w-32 min-w-32 bg-white shadow-[0_0_0_0.5rem_white]"
                  >
                    Matrícula
                  </th>
                  <th scope="col">Marca</th>
                  <th scope="col">Loja</th>
                  <th scope="col">Venda</th>
                  <th scope="col">Cargo</th>
                  <th scope="col">Comissão atual</th>
                  <th scope="col">Comissão simulada</th>
                  <th scope="col">Diferença</th>
                  <th scope="col">Contribuições da regra</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="linha in visiveis" :key="`${linha.competencia}/${linha.matricula}`">
                  <td
                    class="sticky left-2 z-[1] w-28 min-w-28 rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2 shadow-[0_0_0_0.5rem_white]"
                  >
                    {{ competencia(linha.competencia) }}
                  </td>
                  <td
                    class="sticky left-32 z-[1] w-32 min-w-32 rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2 shadow-[0_0_0_0.5rem_white]"
                  >
                    {{ linha.matricula }}
                  </td>
                  <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                    {{ linha.cod_marca }}
                  </td>
                  <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                    {{ linha.cod_loja }}
                  </td>
                  <td
                    class="whitespace-nowrap rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2"
                  >
                    {{ linha.vendas === undefined ? '—' : formatarReais(linha.vendas) }}
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
            <p role="status">Página {{ pagina + 1 }} · {{ linhasFiltradas.length }} registros</p>
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
                :disabled="(pagina + 1) * 25 >= linhasFiltradas.length"
                class="cursor-pointer rounded-lg border border-[#DFC0B2] px-4 py-2 text-[#9D4400] disabled:cursor-default disabled:opacity-50"
                @click="pagina += 1"
              >
                Próxima
              </button>
            </nav>
          </div>
        </template>
      </template>
    </div>
  </section>
</template>
