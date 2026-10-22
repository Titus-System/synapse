<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { storeToRefs } from 'pinia'
import simboloSynapse from '@/assets/imagens/synapse-simbolo.png'
import { usarStoreRenomearRegra, limiteDoNome } from '@/stores/renomearRegra'

interface RegraRecente {
  identificador: string
  rotulo: string
}

withDefaults(
  defineProps<{
    secaoAtiva?: 'salvas' | 'arquivadas'
    quantidadeArquivadas?: number
    quantidadeSalvas?: number
    regrasRecentes?: readonly RegraRecente[]
  }>(),
  {
    secaoAtiva: undefined,
    quantidadeArquivadas: 0,
    quantidadeSalvas: 0,
    regrasRecentes: () => [],
  },
)

const renomear = usarStoreRenomearRegra()
const { idEmEdicao, texto, enviando, erro, tamanho, mensagemDeValidacao, podeConfirmar } =
  storeToRefs(renomear)
const campo = ref<HTMLInputElement[] | HTMLInputElement | null>(null)

async function editar(regra: RegraRecente): Promise<void> {
  renomear.iniciar(regra.identificador, regra.rotulo)
  await nextTick()
  const el = Array.isArray(campo.value) ? campo.value[0] : campo.value
  el?.focus()
  el?.select()
}

function confirmar(): void {
  if (podeConfirmar.value) void renomear.confirmar()
}

function aoSair(): void {
  if (!enviando.value) renomear.cancelar()
}
</script>

<template>
  <aside class="flex h-full min-h-0 flex-col overflow-y-auto bg-[#3b2318] p-5 text-[#f6eae3]">
    <div class="flex items-center gap-3">
      <img :src="simboloSynapse" alt="" class="size-9 object-contain" aria-hidden="true" />
      <span class="font-serif text-xl font-bold tracking-tight">Synapse</span>
    </div>

    <RouterLink
      to="/nova-regra"
      class="mt-6 flex h-11 items-center justify-center gap-2 rounded-[.625rem] bg-[#f26b0f] text-sm font-medium text-white transition hover:bg-[#d95c08]"
    >
      <svg class="size-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
        <path d="M8 3.5v9M3.5 8h9" />
      </svg>
      Nova Regra
    </RouterLink>

    <section class="mt-4" aria-labelledby="titulo-recentes">
      <h2 id="titulo-recentes" class="text-sm font-normal text-[#c7afa3]">Recentes</h2>
      <ul class="mt-3 space-y-2">
        <li v-for="regra in regrasRecentes" :key="regra.identificador">
          <div v-if="idEmEdicao === regra.identificador" class="rounded-[.625rem] bg-[#4d3125] p-2">
            <input
              ref="campo"
              v-model="texto"
              type="text"
              :disabled="enviando"
              :aria-label="`Novo nome da regra ${regra.rotulo}`"
              :aria-invalid="mensagemDeValidacao !== '' || erro !== ''"
              class="h-8 w-full rounded-md border border-[#7a5442] bg-[#3b2318] px-2 text-sm text-[#f6eae3] outline-none focus:border-[#f26b0f] disabled:opacity-60"
              @keydown.enter.prevent="confirmar"
              @keydown.esc.prevent="renomear.cancelar()"
              @blur="aoSair"
            />
            <div class="mt-1 flex items-center justify-between gap-2 text-xs text-[#c7afa3]">
              <span v-if="mensagemDeValidacao || erro" role="alert" class="text-[#ffb59a]">
                {{ erro || mensagemDeValidacao }}
              </span>
              <span v-else>Enter confirma · Esc cancela</span>
              <span class="shrink-0">{{ tamanho }}/{{ limiteDoNome }}</span>
            </div>
          </div>
          <div v-else class="group relative">
            <RouterLink
              :to="`/jobs/${regra.identificador}`"
              :title="regra.rotulo"
              class="flex h-10 min-w-0 items-center rounded-[.625rem] bg-[#4d3125] pr-10 pl-4 text-sm text-[#eaddd5] transition hover:bg-[#5a3b2c]"
            >
              <span class="min-w-0 flex-1 truncate">{{ regra.rotulo }}</span>
            </RouterLink>
            <button
              type="button"
              :aria-label="`Renomear a regra ${regra.rotulo}`"
              class="absolute top-1/2 right-2 grid size-7 -translate-y-1/2 place-items-center rounded-md text-[#d6bdb0] opacity-100 transition hover:bg-[#6b4535] focus-visible:opacity-100 group-focus-within:opacity-100 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100"
              @mousedown.prevent
              @click="editar(regra)"
            >
              <svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M13.5 3.5l3 3L7 16H4v-3l9.5-9.5z" />
              </svg>
            </button>
          </div>
        </li>
        <li v-if="regrasRecentes.length === 0" class="px-1 py-2 text-sm text-[#c7afa3]">
          Nenhuma regra criada ainda.
        </li>
      </ul>
    </section>

    <nav class="mt-auto border-t border-[#5a3e31] pt-3" aria-label="Organização de regras">
      <RouterLink to="/salvas" class="flex items-center gap-3 rounded-lg px-2 py-2.5 text-sm text-[#d6bdb0] transition hover:bg-[#4d3125]" :class="{ 'bg-[#4d3125] text-white': secaoAtiva === 'salvas' }">
        <svg class="size-[1.125rem] shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2.25" />
          <path d="M2.75 8h14.5M7.5 8v8.25" />
        </svg>
        <span class="flex-1">Salvas</span>
        <span class="rounded-full bg-[#4d3125] px-2 py-0.5 text-xs text-[#d6bdb0]">{{ quantidadeSalvas }}</span>
      </RouterLink>
      <RouterLink to="/arquivadas" class="flex items-center gap-3 rounded-lg px-2 py-2.5 text-sm text-[#d6bdb0] transition hover:bg-[#4d3125]" :class="{ 'bg-[#4d3125] text-white': secaoAtiva === 'arquivadas' }">
        <svg class="size-[1.125rem] shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
          <rect x="2.75" y="3.75" width="14.5" height="12.5" rx="2.25" />
          <path d="M2.75 8h14.5M7.5 8v8.25" />
        </svg>
        <span class="flex-1">Arquivadas</span>
        <span class="rounded-full bg-[#4d3125] px-2 py-0.5 text-xs text-[#d6bdb0]">{{ quantidadeArquivadas }}</span>
      </RouterLink>
    </nav>
  </aside>
</template>
