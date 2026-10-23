<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { rotuloDaRegra } from '@/services/job'
import { usarStoreRenomearRegra, limiteDoNome } from '@/stores/renomearRegra'
import type { Job, RegraVersionada, Simulacao } from '@/types/api'
import { transformarRegra, transformarResultado } from '@/composables/transformarRegra'

const props = defineProps<{
  regra?: RegraVersionada
  simulacao?: Simulacao | null
  job?: Pick<Job, 'id' | 'nome' | 'criado_em'> | null
  carregando: boolean
  erro: boolean
}>()

const dataRegra = computed(() =>
  props.regra
    ? new Date(props.regra.criada_em).toLocaleString('pt-BR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '',
)
const baixaRastreabilidade = computed(() => props.simulacao?.flag_baixa_rastreabilidade === true)
const tituloRegra = computed(() => (props.job ? rotuloDaRegra(props.job) : 'Nova Regra'))

const renomear = usarStoreRenomearRegra()
const {
  idEmEdicao,
  texto,
  enviando,
  erro: erroRenomear,
  tamanho,
  mensagemDeValidacao,
  podeConfirmar,
} = storeToRefs(renomear)
const campo = ref<HTMLInputElement | null>(null)
const editando = computed(() => props.job != null && idEmEdicao.value === props.job.id)

async function editarNome(): Promise<void> {
  if (!props.job) return
  renomear.iniciar(props.job.id, tituloRegra.value)
  await nextTick()
  campo.value?.focus()
  campo.value?.select()
}

function confirmarNome(): void {
  if (podeConfirmar.value) void renomear.confirmar()
}

function aoSairNome(): void {
  if (!enviando.value) renomear.cancelar()
}

const regraFormatada = computed(() =>
  props.regra ? transformarRegra(props.regra.representacao) : { se: [], entao: [] },
)
const resultadoFormatado = computed(() =>
  props.simulacao?.status === 'sucesso' && props.simulacao.resultado
    ? transformarResultado(props.simulacao.resultado)
    : [],
)
</script>

<template>
  <div class="flex w-full min-w-0 flex-col rounded-xl border-2 border-[#DFC0B2] bg-white">
    <div class="shrink-0 px-4 pt-7 pb-3 sm:px-8 sm:pt-8">
      <div>
        <div v-if="editando">
          <input
            ref="campo"
            v-model="texto"
            type="text"
            :disabled="enviando"
            aria-label="Novo nome da regra"
            :aria-invalid="mensagemDeValidacao !== '' || erroRenomear !== ''"
            class="mb-1 h-10 w-full rounded-2xl px-3 py-2 border border-[#DFC0B2] text-xl font-bold outline-none focus:bg-[#FFF1EC] disabled:opacity-60"
            @keydown.enter.prevent="confirmarNome"
            @keydown.esc.prevent="renomear.cancelar()"
            @blur="aoSairNome"
          />
          <div class="mb-2 flex items-center justify-between gap-2 text-xs text-[#584237]">
            <span v-if="mensagemDeValidacao || erroRenomear" role="alert" class="text-[#950606]">
              {{ erroRenomear || mensagemDeValidacao }}
            </span>
            <span v-else>
              <span class="hidden lg:inline">Enter confirma · Esc cancela</span>
              <span class="lg:hidden">Enter confirma · Toque fora para cancelar</span>
            </span>
            <span class="shrink-0">{{ tamanho }}/{{ limiteDoNome }}</span>
          </div>
        </div>
        <div v-else class="flex min-w-0 flex-row items-center justify-between gap-4">
          <div class="min-w-0">
            <h2 class="mb-2 text-2xl font-bold break-words">
              {{ carregando ? 'Carregando regra...' : tituloRegra }}
            </h2>
            <div class="flex flex-row gap-2">
              <span v-if="!erro" class="text-sm text-[#9D4400]">Extraída</span>
              <template v-if="regra">
                <p class="text-sm text-[#9D4400]">•</p>
                <span class="text-sm text-[#9D4400]">versão {{ regra.versao }}</span>
              </template>
              <template v-if="dataRegra">
                <p class="text-sm text-[#9D4400]">•</p>
                <span class="text-sm text-[#9D4400]">{{ dataRegra }}</span>
              </template>
            </div>
          </div>
          <div>
            <button
              v-if="job && !carregando && !erro"
              type="button"
              class="shrink-0 cursor-pointer rounded-2xl border border-[#DFC0B2] px-5 py-1 text-[16px] text-[#5C4035] bg-[#FFE0D6] hover:bg-[#fec5b3]"
              @mousedown.prevent
              @click="editarNome"
            >
              Editar
            </button>
          </div>
        </div>
        <div
          v-if="baixaRastreabilidade"
          class="mt-3 rounded-lg border border-[#FFDBCD] bg-[#fdf7f3] px-4 py-3 text-[#765B1A]"
        >
          <p class="mb-1 font-bold">Baixa rastreabilidade</p>
          <p class="text-sm">
            Não foi possível rastrear detalhadamente as decisões tomadas durante a simulação.
          </p>
        </div>
      </div>
    </div>
    <hr class="mb-3 w-[94%] shrink-0 self-center border border-[#FFDBCD]" />
    <div
      class="mx-4 mb-4 min-h-0 overflow-y-auto rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-4 text-[#584237] sm:mx-8"
    >
      <div v-if="carregando" class="flex flex-col items-center justify-center gap-3 py-8">
        <div
          class="h-7 w-7 animate-spin rounded-full border-4 border-[#FFDBCD] border-t-[#F47521]"
        ></div>
        <p class="text-[#584237]">Carregando dados da regra...</p>
      </div>
      <div
        v-else-if="erro"
        class="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center"
      >
        <div
          class="flex h-12 w-12 items-center justify-center rounded-full bg-[#ffc1b0] text-2xl font-bold text-[#950606]"
        >
          !
        </div>
        <h3 class="text-2xl font-bold text-[rgb(149,6,6)]">
          Um erro impossibilitou o carregamento da regra.
        </h3>
        <p class="text-lg text-[#950606]">Por favor, tente novamente.</p>
      </div>
      <div v-else class="flex flex-col gap-3">
        <p class="text-xl font-bold text-[#584237]/70">LÓGICA ESTRUTURADA (PRÉ-VISUALIZAÇÃO)</p>
        <div>
          <h3 class="mb-1 text-base font-bold">SE</h3>
          <div class="flex flex-col gap-1 pl-6">
            <p v-for="(linha, indice) in regraFormatada.se" :key="`se-${indice}`" class="text-sm">
              {{ linha }}
            </p>
          </div>
        </div>
        <div>
          <h3 class="mb-1 text-base font-bold">ENTÃO</h3>
          <div class="flex flex-col gap-2 pl-6">
            <p
              v-for="(linha, indice) in [...regraFormatada.entao, ...resultadoFormatado]"
              :key="`entao-${indice}`"
              class="text-sm"
            >
              {{ linha }}
            </p>
          </div>
        </div>
      </div>
    </div>
    <slot />
  </div>
</template>