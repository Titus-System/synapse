<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    id: string
    rotulo: string
    valores: readonly string[]
    opcoes: readonly { valor: string; rotulo: string }[]
    resumoPlural: string
    erro?: string
    ajuda?: string
    compacto?: boolean
  }>(),
  { erro: '', ajuda: '', compacto: false },
)

const emitir = defineEmits<{ 'update:valores': [valores: string[]] }>()

const raiz = ref<HTMLElement | null>(null)
const aberto = ref(false)
const filtro = ref('')

const opcoesFiltradas = computed(() => {
  const termo = filtro.value.trim().toLowerCase()
  if (!termo) return props.opcoes

  return props.opcoes.filter(
    (opcao) => opcao.rotulo.toLowerCase().includes(termo) || opcao.valor.includes(termo),
  )
})

const resumo = computed(() => {
  if (props.valores.length === 0) return 'Selecione uma opção'
  if (props.valores.length > 1) return `${props.valores.length} ${props.resumoPlural}`

  const selecionado = props.opcoes.find((opcao) => opcao.valor === props.valores[0])
  return selecionado ? selecionado.rotulo : (props.valores[0] ?? '')
})

function estaSelecionado(valor: string): boolean {
  return props.valores.includes(valor)
}

function alternarOpcao(valor: string): void {
  // A ordem das opções é mantida na seleção para que o mesmo conjunto de
  // códigos chegue sempre na mesma ordem à requisição.
  const selecionados = props.opcoes
    .map((opcao) => opcao.valor)
    .filter((codigo) => (codigo === valor ? !estaSelecionado(codigo) : estaSelecionado(codigo)))

  emitir('update:valores', selecionados)
}

function alternarPainel(): void {
  aberto.value = !aberto.value
}

function fecharPainel(): void {
  aberto.value = false
}

function fecharAoClicarFora(evento: MouseEvent): void {
  const alvo = evento.target
  if (alvo instanceof Node && !raiz.value?.contains(alvo)) fecharPainel()
}

watch(aberto, (estaAberto) => {
  if (!estaAberto) filtro.value = ''
})

onMounted(() => {
  document.addEventListener('click', fecharAoClicarFora)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', fecharAoClicarFora)
})
</script>

<template>
  <div ref="raiz" @keydown.esc="fecharPainel">
    <label :for="id" :class="compacto ? 'sr-only' : 'block text-sm font-medium text-[#3a241a]'">{{ rotulo }}</label>
    <p v-if="ajuda" :id="`${id}-ajuda`" :class="compacto ? 'sr-only' : 'mt-1 text-sm text-[#6b564a]'">{{ ajuda }}</p>
    <div :class="compacto ? 'relative' : 'relative mt-2'">
      <button
        :id="id"
        type="button"
        aria-haspopup="true"
        :aria-expanded="aberto"
        :aria-controls="`${id}-painel`"
        :aria-invalid="Boolean(erro)"
        :aria-describedby="[ajuda ? `${id}-ajuda` : '', erro ? `${id}-erro` : ''].filter(Boolean).join(' ') || undefined"
        class="flex h-[2.125rem] w-full cursor-pointer items-center rounded-[.4375rem] border bg-[#faf4ef] pr-8 pl-3 text-left text-sm outline-none transition focus:border-[#c2560b] focus:ring-2 focus:ring-[#f4dcc9]"
        :class="[
          erro ? 'border-[#c0392b]' : 'border-[#e3d3c9]',
          valores.length === 0 ? 'text-[#b09a8d]' : 'text-[#2e1a10]',
          compacto ? '' : 'mt-2 h-11 bg-white',
        ]"
        @click="alternarPainel"
      >
        <span class="truncate">{{ resumo }}</span>
      </button>
      <svg
        class="pointer-events-none absolute top-1/2 right-3 size-3 -translate-y-1/2 text-[#8a7366]"
        viewBox="0 0 12 12"
        fill="currentColor"
        aria-hidden="true"
      >
        <path d="M2 4.25h8L6 9z" />
      </svg>

      <div
        v-if="aberto"
        :id="`${id}-painel`"
        role="group"
        :aria-label="rotulo"
        class="absolute top-full right-0 left-0 z-20 mt-1 overflow-hidden rounded-[.4375rem] border border-[#e3d3c9] bg-white shadow-[0_18px_40px_-20px_rgba(60,30,15,0.5)]"
      >
        <div class="border-b border-[#eee2da] p-2">
          <input
            v-model="filtro"
            type="search"
            @keydown.enter.prevent
            :placeholder="`Filtrar ${rotulo.toLowerCase()}`"
            :aria-label="`Filtrar ${rotulo.toLowerCase()}`"
            class="h-8 w-full rounded-[.375rem] border border-[#e3d3c9] bg-[#faf4ef] px-2 text-sm text-[#2e1a10] outline-none transition placeholder:text-[#b09a8d] focus:border-[#c2560b]"
          />
        </div>
        <ul class="max-h-52 overflow-y-auto py-1">
          <li v-for="opcao in opcoesFiltradas" :key="opcao.valor">
            <label class="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm text-[#2e1a10] transition hover:bg-[#fdf9f6]">
              <input
                type="checkbox"
                :checked="estaSelecionado(opcao.valor)"
                class="size-3.5 shrink-0 accent-[#c2560b]"
                @change="alternarOpcao(opcao.valor)"
              />
              <span>{{ opcao.rotulo }}</span>
            </label>
          </li>
          <li v-if="opcoesFiltradas.length === 0" class="px-3 py-2 text-sm text-[#8a7366]">
            Nenhuma opção encontrada.
          </li>
        </ul>
      </div>
    </div>
    <p v-if="erro" :id="`${id}-erro`" class="mt-1.5 text-sm text-[#c0392b]" role="alert">{{ erro }}</p>
  </div>
</template>
