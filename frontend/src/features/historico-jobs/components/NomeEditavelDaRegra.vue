<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { rotuloDaRegra } from '@/services/job'
import { limiteDoNome, usarStoreRenomearRegra } from '@/stores/renomearRegra'
import type { JobResumo } from '@/types/api'

const props = defineProps<{ resumo: JobResumo }>()

const renomear = usarStoreRenomearRegra()
const rotulo = computed(() =>
  renomear.rotuloExibido(props.resumo.id, rotuloDaRegra(props.resumo)),
)
const criadaEm = computed(() => new Date(props.resumo.criado_em).toLocaleDateString('pt-BR'))
const { idEmEdicao, texto, enviando, erro, tamanho, mensagemDeValidacao, podeConfirmar } =
  storeToRefs(renomear)
const campo = ref<HTMLInputElement | null>(null)
const editando = computed(() => idEmEdicao.value === props.resumo.id)

async function editar(): Promise<void> {
  renomear.iniciar(props.resumo.id, rotulo.value)
  await nextTick()
  campo.value?.focus()
  campo.value?.select()
}

function confirmar(): void {
  if (podeConfirmar.value) void renomear.confirmar()
}

function aoSair(): void {
  if (!enviando.value) renomear.cancelar()
}
</script>

<template>
  <div class="min-w-0">
    <div v-if="editando">
      <input
        ref="campo"
        v-model="texto"
        type="text"
        :disabled="enviando"
        aria-label="Novo nome da regra"
        :aria-invalid="mensagemDeValidacao !== '' || erro !== ''"
        class="mb-1 h-10 w-full rounded-2xl border border-[#DFC0B2] px-3 py-2 font-serif text-xl font-semibold outline-none focus:bg-[#FFF1EC] disabled:opacity-60"
        @keydown.enter.prevent="confirmar"
        @keydown.esc.prevent="renomear.cancelar()"
        @blur="aoSair"
      />
      <div class="flex items-center justify-between gap-2 text-xs text-[#584237]">
        <span v-if="mensagemDeValidacao || erro" role="alert" class="text-[#950606]">
          {{ erro || mensagemDeValidacao }}
        </span>
        <span v-else>
          <span class="hidden lg:inline">Enter confirma · Esc cancela</span>
          <span class="lg:hidden">Enter confirma · Toque fora para cancelar</span>
        </span>
        <span class="shrink-0">{{ tamanho }}/{{ limiteDoNome }}</span>
      </div>
    </div>
    <h2 v-else class="font-serif text-2xl font-semibold break-words">{{ rotulo }}</h2>
    <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
      <p class="text-sm text-[#9c571e]">Criada em {{ criadaEm }}</p>
      <button
        v-if="!editando"
        type="button"
        :aria-label="`Editar o nome da regra ${rotulo}`"
        class="shrink-0 cursor-pointer rounded-full border border-[#edd0c0] bg-[#fff3ec] px-3 py-1 text-xs font-medium text-[#8f470e] transition hover:bg-[#ffe6da] hover:text-[#843600]"
        @mousedown.prevent
        @click="editar"
      >
        Editar
      </button>
    </div>
  </div>
</template>
