<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { codigosAuditoria, dataAuditoria } from '../composables/apresentacaoAuditoria'
import type { ChamadaModeloAuditoria, CodigoAuditoria, VersaoAuditoria } from '../types'

interface CodigoLigado {
  codigo: CodigoAuditoria
  versao?: VersaoAuditoria
  chamada?: ChamadaModeloAuditoria
}
const props = defineProps<{ codigos: CodigoLigado[] }>()

const selecionado = ref(0)
const copia = ref<'ocioso' | 'copiado' | 'falhou'>('ocioso')
const atual = computed(() => props.codigos[selecionado.value])
// O fonte termina em \n: sem descartar a última linha vazia, a tela numeraria uma linha fantasma.
const linhas = computed(() => {
  const partes = (atual.value?.codigo.fonte ?? '').split('\n')
  if (partes.length > 1 && partes[partes.length - 1] === '') partes.pop()
  return partes
})
const nucleo = computed(() => atual.value?.versao?.representacao.nucleo)

watch(
  () => props.codigos,
  () => {
    selecionado.value = 0
    copia.value = 'ocioso'
  },
)
watch(selecionado, () => (copia.value = 'ocioso'))

async function copiar() {
  if (!atual.value) return
  try {
    await navigator.clipboard.writeText(atual.value.codigo.fonte)
    copia.value = 'copiado'
  } catch {
    copia.value = 'falhou'
  }
}
function rotulo(item: CodigoLigado) {
  return `${item.codigo.id}${item.versao ? ` · v${item.versao.versao}` : ''}`
}
</script>
<template>
  <section
    class="flex h-full min-h-0 flex-col rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm"
    aria-label="Código gerado"
  >
    <h2 class="font-serif text-2xl font-bold text-[#2e1a10]">Código gerado</h2>
    <p v-if="!atual" class="mt-4">Nenhum código registrado.</p>
    <template v-else>
      <label v-if="codigos.length > 1" class="mt-4 flex flex-col gap-2 text-sm">
        Código
        <select v-model="selecionado" class="rounded-lg border border-[#dec0b1] bg-white p-2">
          <option v-for="(item, indice) in codigos" :key="item.codigo.id" :value="indice">
            {{ rotulo(item) }}
          </option>
        </select>
      </label>
      <dl class="mt-4 grid gap-2 text-sm sm:grid-cols-2">
        <div class="break-all">
          <dt class="text-[#806b5d]">Código</dt>
          <dd class="font-semibold">{{ atual.codigo.id }}</dd>
        </div>
        <div>
          <dt class="text-[#806b5d]">Versão da regra</dt>
          <dd class="font-semibold">
            {{ atual.versao ? `v${atual.versao.versao}` : 'Não identificada' }}
          </dd>
        </div>
        <div>
          <dt class="text-[#806b5d]">Linguagem · registro</dt>
          <dd class="font-semibold">
            {{ atual.codigo.linguagem }} · {{ dataAuditoria(atual.codigo.criado_em) }}
          </dd>
        </div>
        <div>
          <dt class="text-[#806b5d]">Loja / marca / cargo</dt>
          <dd class="font-semibold" data-escopo>
            {{ codigosAuditoria(nucleo?.loja) }} / {{ codigosAuditoria(nucleo?.marca) }} /
            {{ codigosAuditoria(nucleo?.cargo) }}
          </dd>
        </div>
      </dl>
      <div class="mt-4 flex items-center gap-3">
        <button
          type="button"
          class="cursor-pointer rounded-lg border border-[#a74700] px-4 py-2 text-sm font-semibold text-[#a74700] transition hover:bg-[#fff0e9] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#a74700]"
          @click="copiar"
        >
          Copiar código
        </button>
        <span v-if="copia === 'copiado'" role="status" class="text-sm">Código copiado.</span>
        <span v-else-if="copia === 'falhou'" role="alert" class="text-sm">
          Não foi possível copiar. Por favor, selecione o texto manualmente.
        </span>
      </div>
      <div
        class="mt-4 min-h-0 flex-1 overflow-auto rounded-xl bg-[#2f241f] p-4 font-mono text-xs leading-6 text-[#f6eae3]"
        tabindex="0"
        aria-label="Fonte do código"
      >
        <div v-for="(linha, indice) in linhas" :key="indice" class="flex gap-4" data-linha>
          <span class="w-8 shrink-0 select-none text-right text-[#a38a7e]">{{ indice + 1 }}</span>
          <span class="whitespace-pre">{{ linha }}</span>
        </div>
      </div>
    </template>
  </section>
</template>