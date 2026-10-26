<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { nomeDaEntidade } from '@/services/catalogoRh'
import type { ResultadoSimulacao } from '@/types/api'
import { formatarReais } from '@/composables/apresentacaoDetalhamento'

const props = defineProps<{
  decomposicao?: ResultadoSimulacao['decomposicao']
  matricula: string
  loja: string | string[]
  competencia: string | string[]
}>()
const paginas = ref<Record<string, number>>({})
const grupos = computed(() =>
  [
    {
      chave: 'matricula',
      titulo: 'Por colaborador',
      filtro: props.matricula ? [props.matricula] : [],
    },
    {
      chave: 'loja_absoluto',
      titulo: 'Por loja',
      filtro: Array.isArray(props.loja) ? props.loja : props.loja ? [props.loja] : [],
    },
    {
      chave: 'competencia_absoluto',
      titulo: 'Por competência',
      filtro: Array.isArray(props.competencia)
        ? props.competencia
        : props.competencia
          ? [props.competencia]
          : [],
    },
  ].map((grupo) => ({
    ...grupo,
    disponivel: props.decomposicao?.[grupo.chave] != null,
    itens: Object.entries(props.decomposicao?.[grupo.chave] ?? {}).filter(([chave]) =>
      grupo.chave === 'matricula'
        ? chave.toLocaleLowerCase('pt-BR').includes(props.matricula.toLocaleLowerCase('pt-BR'))
        : !grupo.filtro.length || grupo.filtro.includes(chave),
    ),
  })),
)

watch(
  () => [props.matricula, props.loja, props.competencia, props.decomposicao],
  () => {
    paginas.value = {}
  },
)
</script>

<template>
  <section class="mb-5" aria-label="Totais da simulação">
    <h3 class="font-bold">Totais da Simulação</h3>
    <p class="mb-3 text-sm">
      Colaborador e loja: período completo. Competência: total do mês. Cada grupo considera apenas o
      filtro correspondente.
    </p>
    <div class="grid items-start gap-3 sm:grid-cols-3">
      <details
        v-for="grupo in grupos"
        :key="grupo.chave"
        class="min-w-0 rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-3"
      >
        <summary class="cursor-pointer font-bold">{{ grupo.titulo }}</summary>
        <p v-if="!grupo.disponivel" class="mt-3 text-sm">
          Os totais deste grupo não estão disponíveis para esta simulação.
        </p>
        <p v-else-if="!grupo.itens.length" class="mt-3 text-sm">
          Nenhum total encontrado para este filtro.
        </p>
        <template v-else>
          <dl class="mt-3 max-h-64 space-y-2 overflow-auto text-sm">
            <div
              v-for="[chave, valor] in grupo.itens.slice(
                (paginas[grupo.chave] ?? 0) * 25,
                ((paginas[grupo.chave] ?? 0) + 1) * 25,
              )"
              :key="chave"
              class="flex flex-wrap justify-between gap-2 border-b border-[#FFDBCD] pb-2"
            >
              <dt>
                {{
                  grupo.chave === 'competencia_absoluto'
                    ? chave.split('-').reverse().join('/')
                    : grupo.chave === 'loja_absoluto'
                      ? nomeDaEntidade('loja', chave)
                      : chave
                }}
              </dt>
              <dd class="font-bold">{{ formatarReais(valor) }}</dd>
            </div>
          </dl>
          <nav
            v-if="grupo.itens.length > 25"
            :aria-label="`Páginas dos totais ${grupo.titulo.toLowerCase()}`"
            class="mt-3 flex flex-wrap items-center gap-2 text-sm"
          >
            <button
              type="button"
              :disabled="!paginas[grupo.chave]"
              class="cursor-pointer underline disabled:cursor-default disabled:opacity-50"
              @click="paginas[grupo.chave] = (paginas[grupo.chave] ?? 0) - 1"
            >
              Anterior
            </button>
            <span>{{ (paginas[grupo.chave] ?? 0) + 1 }}</span>
            <button
              type="button"
              :disabled="((paginas[grupo.chave] ?? 0) + 1) * 25 >= grupo.itens.length"
              class="cursor-pointer underline disabled:cursor-default disabled:opacity-50"
              @click="paginas[grupo.chave] = (paginas[grupo.chave] ?? 0) + 1"
            >
              Próxima
            </button>
          </nav>
        </template>
      </details>
    </div>
  </section>
</template>
