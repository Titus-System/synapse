<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { RepresentacaoRegra, ResultadoLinhas, ResultadoSimulacao } from '@/types/api'
import TabelaDetalhamento from '@/components/TabelaDetalhamento.vue'
import TotaisDetalhamento from '@/components/TotaisDetalhamento.vue'
import FiltrosRelatorio from './FiltrosRelatorio.vue'
import { filtrarLinhas, filtrosVazios, linhasDoEscopo } from '../composables/filtrosRelatorio'

const props = defineProps<{
  aberto: boolean
  carregando: boolean
  erro: string | null
  linhas?: ResultadoLinhas
  regra?: RepresentacaoRegra
  competenciasDoJob?: string[]
  decomposicao?: ResultadoSimulacao['decomposicao']
}>()
const emitir = defineEmits<{ alternar: []; tentarNovamente: [] }>()
const dialogo = ref<HTMLDialogElement>()
const acionador = ref<HTMLButtonElement>()
const resultado = ref<HTMLElement>()
const editando = ref(true)
const filtros = ref(filtrosVazios())
const aplicados = ref(filtrosVazios())
const escopo = computed(() =>
  linhasDoEscopo(props.linhas ?? {}, props.regra, props.competenciasDoJob),
)
const linhasFiltradas = computed(() => filtrarLinhas(escopo.value, aplicados.value))
const opcoes = computed(() => ({
  loja: [...new Set(escopo.value.map((linha) => linha.cod_loja))],
  marca: [...new Set(escopo.value.map((linha) => linha.cod_marca))],
  cargo: [...new Set(escopo.value.map((linha) => linha.cod_cargo))],
  competencia: [...new Set(escopo.value.map((linha) => linha.competencia))].sort(),
}))
const escopoLegado = computed(() =>
  (['loja', 'marca', 'cargo'] as const).some((dimensao) => props.regra?.nucleo[dimensao] == null),
)
const temDetalhamento = computed(() =>
  Object.values(props.linhas ?? {}).some((mes) => Object.keys(mes).length),
)
async function aplicar() {
  aplicados.value = {
    ...filtros.value,
    loja: [...filtros.value.loja],
    marca: [...filtros.value.marca],
    cargo: [...filtros.value.cargo],
    competencia: [...filtros.value.competencia],
  }
  editando.value = false
  await nextTick()
  resultado.value?.focus({ preventScroll: true })
  if (dialogo.value) dialogo.value.scrollTop = 0
}
async function alterarFiltros() {
  editando.value = true
  await nextTick()
  dialogo.value?.querySelector<HTMLInputElement>('form input')?.focus({ preventScroll: true })
  if (dialogo.value) dialogo.value.scrollTop = 0
}
function manterFoco(evento: KeyboardEvent) {
  if (evento.key !== 'Tab') return
  const controles = Array.from(dialogo.value?.querySelectorAll<HTMLElement>('*') ?? []).filter(
    (elemento) =>
      elemento.matches(
        'button:not(:disabled), input:not(:disabled), select:not(:disabled), summary, a[href], [tabindex]:not([tabindex="-1"])',
      ) && elemento.getClientRects().length > 0,
  )
  const primeiro = controles[0]
  const ultimo = controles[controles.length - 1]
  if (!primeiro || !ultimo) return
  if (evento.shiftKey && document.activeElement === primeiro) {
    evento.preventDefault()
    ultimo.focus()
  } else if (!evento.shiftKey && document.activeElement === ultimo) {
    evento.preventDefault()
    primeiro.focus()
  }
}
watch(
  () => props.aberto,
  async (aberto) => {
    await nextTick()
    if (aberto) {
      editando.value = true
      filtros.value = {
        ...aplicados.value,
        loja: [...aplicados.value.loja],
        marca: [...aplicados.value.marca],
        cargo: [...aplicados.value.cargo],
        competencia: [...aplicados.value.competencia],
      }
      if (!dialogo.value?.open) dialogo.value?.showModal()
    } else if (dialogo.value?.open) {
      dialogo.value.close()
      acionador.value?.focus()
    }
  },
  { immediate: true },
)
</script>
<template>
  <button
    ref="acionador"
    type="button"
    aria-haspopup="dialog"
    class="rounded-lg border border-[#DFC0B2] px-4 py-2 text-[#9D4400]"
    @click="emitir('alternar')"
  >
    Abrir relatório
  </button>
  <dialog
    ref="dialogo"
    aria-labelledby="titulo-relatorio"
    class="m-auto max-h-[90dvh] w-[min(95vw,80rem)] overflow-y-auto rounded-xl border border-[#DFC0B2] bg-white p-4 text-[#584237] shadow-xl backdrop:bg-black/50 sm:p-6"
    @cancel.prevent="emitir('alternar')"
    @keydown="manterFoco"
  >
    <header class="sticky top-0 z-20 mb-5 flex items-center justify-between gap-3 bg-white">
      <h2 id="titulo-relatorio" class="text-xl font-bold">Relatório da simulação</h2>
      <button
        type="button"
        autofocus
        class="rounded-lg border border-[#DFC0B2] px-3 py-2"
        @click="emitir('alternar')"
      >
        Fechar relatório
      </button>
    </header>
    <div :aria-busy="carregando">
      <p v-if="carregando" role="status">Carregando relatório...</p>
      <div v-else-if="erro" role="alert">
        <p>{{ erro }}</p>
        <button type="button" class="mt-3 underline" @click="emitir('tentarNovamente')">
          Tentar novamente
        </button>
      </div>
      <p v-else-if="!temDetalhamento" role="status">
        O detalhamento não está disponível para esta simulação.
      </p>
      <template v-else>
        <p v-if="escopoLegado" class="mb-4 text-sm">
          Esta versão não registrou todas as dimensões de escopo explicitamente. O relatório
          preserva a abrangência do resultado histórico nas dimensões ausentes.
        </p>
        <FiltrosRelatorio
          v-if="editando"
          v-model="filtros"
          :opcoes="opcoes"
          @aplicar="aplicar"
          @limpar="filtros = filtrosVazios()"
        />
        <section v-else ref="resultado" tabindex="-1" aria-label="Resultado do relatório">
          <button
            type="button"
            class="mb-4 rounded-lg border border-[#DFC0B2] px-4 py-2"
            @click="alterarFiltros"
          >
            Alterar filtros
          </button>
          <TabelaDetalhamento :linhas="linhasFiltradas" :regra="regra" />
          <TotaisDetalhamento
            class="mt-6"
            :decomposicao="decomposicao"
            :matricula="aplicados.matricula"
            :loja="aplicados.loja"
            :competencia="aplicados.competencia"
          />
        </section>
      </template>
    </div>
  </dialog>
</template>
