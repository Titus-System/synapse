<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import TheSidebar from '@/components/TheSidebar.vue'
import { apiClient } from '@/services/api'
import type { JobResumo } from '@/types/api'
import CampoDeSelecao from '../components/CampoDeSelecao.vue'
import CampoDeTexto from '../components/CampoDeTexto.vue'
import { useFormularioRegra } from '../composables/useFormularioRegra'

const roteador = useRouter()
const regrasRecentes = ref<{ identificador: string; rotulo: string }[]>([])
const quantidadeArquivadas = ref(0)
const quantidadeSalvas = ref(0)
const {
  opcoesDeVigencia,
  enviando,
  enviarFormulario,
  erros,
  formatarOrcamentoAoSair,
  formulario,
  mensagemDoFormulario,
} = useFormularioRegra()

function criarRotuloDaRegra(resumoDoJob: JobResumo): string {
  const data = new Date(resumoDoJob.criado_em).toLocaleDateString('pt-BR')
  return `Regra · ${data}`
}

function atualizarContagensDeRegras(resumosDosJobs: readonly JobResumo[]): void {
  quantidadeArquivadas.value = resumosDosJobs.filter((resumoDoJob) => resumoDoJob.status === 'arquivado').length
  quantidadeSalvas.value = resumosDosJobs.length - quantidadeArquivadas.value
}

async function carregarRegrasRecentes(): Promise<void> {
  try {
    const resumosDosJobs: JobResumo[] = []
    let numeroDaPagina = 0
    let totalDeJobs = 0
    let itensDaPagina: JobResumo[] = []

    do {
      const paginaDeJobs = await apiClient.listarJobs({ pagina: numeroDaPagina, tamanho: 100 })
      totalDeJobs = paginaDeJobs.total
      itensDaPagina = paginaDeJobs.itens
      resumosDosJobs.push(...itensDaPagina)
      numeroDaPagina += 1
    } while (resumosDosJobs.length < totalDeJobs && itensDaPagina.length > 0)

    regrasRecentes.value = resumosDosJobs.slice(0, 6).map((resumoDoJob) => ({
      identificador: resumoDoJob.id,
      rotulo: criarRotuloDaRegra(resumoDoJob),
    }))
    atualizarContagensDeRegras(resumosDosJobs)
  } catch {
    regrasRecentes.value = []
    quantidadeArquivadas.value = 0
    quantidadeSalvas.value = 0
  }
}

async function submeterFormulario(): Promise<void> {
  const jobCriado = await enviarFormulario()
  if (!jobCriado) return

  await carregarRegrasRecentes()

  const destino = roteador.resolve(`/jobs/${jobCriado.id}`)
  if (destino.name === 'not-found') {
    mensagemDoFormulario.value = 'Processamento iniciado. O acompanhamento será aberto em seguida.'
    return
  }

  await roteador.push(destino)
}

onMounted(() => {
  void carregarRegrasRecentes()
})
</script>

<template>
  <div class="h-screen overflow-hidden bg-[#fdf7f3] text-[#2e1a10] md:grid md:grid-cols-[clamp(13.5rem,18vw,16.25rem)_1fr] [@media(min-resolution:1.25dppx)]:fixed [@media(min-resolution:1.25dppx)]:top-0 [@media(min-resolution:1.25dppx)]:left-0 [@media(min-resolution:1.25dppx)]:h-[125vh] [@media(min-resolution:1.25dppx)]:w-[125%] [@media(min-resolution:1.25dppx)]:origin-top-left [@media(min-resolution:1.25dppx)]:scale-[.8]">
    <TheSidebar
      class="hidden md:flex"
      :quantidade-arquivadas="quantidadeArquivadas"
      :quantidade-salvas="quantidadeSalvas"
      :regras-recentes="regrasRecentes"
    />

    <main class="flex min-w-0 flex-col bg-[radial-gradient(circle_at_top,#fffdfb_0%,#fdf7f3_48%,#f8eee8_100%)]">
      <header class="flex h-[clamp(2.5rem,7vh,4rem)] items-center gap-6 border-b border-[#ebd8cc] px-6 lg:px-8">
        <div class="flex shrink-0 gap-2" aria-label="Indicadores da janela">
          <span class="size-3 rounded-full bg-[#ff625c]"></span>
          <span class="size-3 rounded-full bg-[#ffbd2e]"></span>
          <span class="size-3 rounded-full bg-[#27c840]"></span>
        </div>
        <ol class="hidden min-w-0 flex-1 items-center justify-center gap-3 text-sm xl:flex" aria-label="Etapas do processo">
          <li class="flex shrink-0 items-center gap-2.5 font-medium text-[#c2560b]"><span class="grid size-[34px] place-items-center rounded-full border-[1.5px] border-[#c2560b]" aria-hidden="true"><svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><rect x="7.25" y="2.75" width="5.5" height="9.5" rx="2.75" /><path d="M4.75 9.5a5.25 5.25 0 0 0 10.5 0M10 14.75v2.5" /></svg></span>Voz/Texto</li>
          <li class="h-px min-w-6 flex-1 bg-[#e5d3c8]" aria-hidden="true"></li>
          <li class="flex shrink-0 items-center gap-2.5 text-[#a79489]"><span class="grid size-[34px] place-items-center rounded-full border border-[#e5d3c8]" aria-hidden="true"><svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M3.25 6.25a2.5 2.5 0 0 1 2.5-2.5h8.5a2.5 2.5 0 0 1 2.5 2.5v5a2.5 2.5 0 0 1-2.5 2.5H8l-4.75 3.25z" /></svg></span>Conversa</li>
          <li class="h-px min-w-6 flex-1 bg-[#e5d3c8]" aria-hidden="true"></li>
          <li class="flex shrink-0 items-center gap-2.5 text-[#a79489]"><span class="grid size-[34px] place-items-center rounded-full border border-[#e5d3c8]" aria-hidden="true"><svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><circle cx="10" cy="10" r="7.25" /><path d="M8.25 7.1 13 10l-4.75 2.9z" /></svg></span>Simulação</li>
          <li class="h-px min-w-6 flex-1 bg-[#e5d3c8]" aria-hidden="true"></li>
          <li class="flex shrink-0 items-center gap-2.5 text-[#a79489]"><span class="grid size-[34px] place-items-center rounded-full border border-[#e5d3c8]" aria-hidden="true"><svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M3.75 5.25a1.5 1.5 0 0 1 1.5-1.5h7.5l3 3v8a1.5 1.5 0 0 1-1.5 1.5h-9a1.5 1.5 0 0 1-1.5-1.5z" /><path d="M6.75 3.75v4h6.5M6.75 16.25v-4h6.5v4" /></svg></span>Salvar</li>
        </ol>
        <details class="relative ml-auto shrink-0">
          <summary class="flex cursor-pointer list-none items-center gap-2 rounded-full border border-[#ead4c7] bg-white/80 py-1 pr-2 pl-1.5 text-sm text-[#5e473b] transition hover:bg-white [&::-webkit-details-marker]:hidden">
            <span class="grid size-7 place-items-center rounded-full bg-[#6d4030] text-xs font-semibold text-white" aria-hidden="true">U</span>
            <span class="hidden lg:block">Perfil</span>
            <svg class="size-3 text-[#9c8174]" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true"><path d="M2 4.25h8L6 9z" /></svg>
          </summary>
          <div class="absolute top-[calc(100%+.5rem)] right-0 z-10 w-52 rounded-lg border border-[#ead4c7] bg-white p-3 shadow-[0_12px_30px_-12px_rgba(60,30,15,0.35)]">
            <p class="text-sm font-semibold text-[#2e1a10]">Perfil do usuário</p>
            <p class="mt-1 text-xs leading-5 text-[#80695c]">A saída da conta será conectada ao login.</p>
            <button type="button" disabled class="mt-3 flex w-full items-center justify-center gap-2 rounded-md border border-[#e4cfc3] px-3 py-2 text-sm font-medium text-[#9c8174] disabled:cursor-not-allowed disabled:opacity-70">
              Sair da conta
            </button>
          </div>
        </details>
      </header>

      <div id="formulario-regra" class="mx-auto w-full max-w-[660px] px-6 py-[clamp(1rem,5vh,3.5rem)]">
        <header class="text-center">
          <p class="inline-flex rounded-full border border-[#ead4c7] bg-white/75 px-3 py-1 text-xs font-semibold tracking-[0.14em] text-[#a54809] uppercase">
            Nova regra
          </p>
          <h1 class="mt-3 font-serif text-[clamp(1.75rem,4vh,2.25rem)] leading-tight font-semibold tracking-tight text-[#2e1a10]">
            Capture uma Regra de Negócio
          </h1>
          <p class="mt-3 text-base text-[#6b564a]">Escreva os parâmetros da regra. Nós iremos estruturá-la para você.</p>
        </header>

        <form
          class="mx-auto mt-[clamp(1rem,3vh,2.25rem)] max-w-[540px] overflow-hidden rounded-xl border border-[#e7d6cb] bg-white shadow-[0_18px_45px_-24px_rgba(60,30,15,0.42)]"
          @submit.prevent="submeterFormulario"
        >
          <div
            class="grid grid-cols-[minmax(0,1fr)_210px] gap-4 border-b border-[#eee2da] bg-[#f8f1ec] px-5 py-[clamp(.5rem,1.5vh,.75rem)] text-sm font-medium text-[#3a241a]"
          >
            <span>Parâmetro</span>
            <span>Valor</span>
          </div>

          <div class="divide-y divide-[#eee2da]">
            <div class="grid grid-cols-[minmax(0,1fr)_210px] items-center gap-4 px-5 py-[clamp(.25rem,1vh,.5rem)] transition hover:bg-[#fdf9f6]">
              <span class="text-sm">Início da vigência</span>
              <CampoDeSelecao
                id="vigencia-inicio"
                v-model:valor="formulario.vigenciaInicio"
                rotulo="Início da vigência"
                :opcoes="opcoesDeVigencia"
                :erro="erros.vigenciaInicio"
                compacto
              />
            </div>
            <div class="grid grid-cols-[minmax(0,1fr)_210px] items-center gap-4 px-5 py-[clamp(.25rem,1vh,.5rem)] transition hover:bg-[#fdf9f6]">
              <span class="text-sm">Fim da vigência</span>
              <CampoDeSelecao
                id="vigencia-fim"
                v-model:valor="formulario.vigenciaFim"
                rotulo="Fim da vigência"
                :opcoes="opcoesDeVigencia"
                :erro="erros.vigenciaFim"
                compacto
              />
            </div>
            <div class="grid grid-cols-[minmax(0,1fr)_210px] items-center gap-4 px-5 py-[clamp(.25rem,1vh,.5rem)] transition hover:bg-[#fdf9f6]">
              <span class="text-sm">Loja</span>
              <CampoDeTexto
                id="loja"
                v-model:valor="formulario.loja"
                rotulo="Loja"
                ajuda="Informe os códigos das lojas separados por vírgula."
                placeholder="Ex.: 13, 21"
                :erro="erros.loja"
                compacto
              />
            </div>
            <div class="grid grid-cols-[minmax(0,1fr)_210px] items-center gap-4 px-5 py-[clamp(.25rem,1vh,.5rem)] transition hover:bg-[#fdf9f6]">
              <span class="text-sm">Marca</span>
              <CampoDeTexto
                id="marca"
                v-model:valor="formulario.marca"
                rotulo="Marca"
                ajuda="Informe os códigos das marcas separados por vírgula."
                placeholder="Ex.: 10, 20"
                :erro="erros.marca"
                compacto
              />
            </div>
            <div class="grid grid-cols-[minmax(0,1fr)_210px] items-center gap-4 px-5 py-[clamp(.25rem,1vh,.5rem)] transition hover:bg-[#fdf9f6]">
              <span class="text-sm">Cargo</span>
              <CampoDeTexto
                id="cargo"
                v-model:valor="formulario.cargo"
                rotulo="Cargo"
                ajuda="Informe os códigos dos cargos separados por vírgula."
                placeholder="Ex.: 100, 300"
                :erro="erros.cargo"
                compacto
              />
            </div>
            <div class="grid grid-cols-[minmax(0,1fr)_210px] items-center gap-4 px-5 py-[clamp(.25rem,1vh,.5rem)] transition hover:bg-[#fdf9f6]">
              <span class="text-sm">% de comissão</span>
              <CampoDeTexto
                id="percentual"
                v-model:valor="formulario.percentual"
                rotulo="Percentual de comissão"
                placeholder="Ex.: 2,5"
                sufixo="%"
                :erro="erros.percentual"
                compacto
              />
            </div>
            <div class="grid grid-cols-[minmax(0,1fr)_210px] items-center gap-4 px-5 py-[clamp(.25rem,1vh,.5rem)] transition hover:bg-[#fdf9f6]">
              <span class="text-sm">Orçamento</span>
              <CampoDeTexto
                id="orcamento"
                v-model:valor="formulario.orcamento"
                rotulo="Orçamento de comissionamento"
                ajuda="Informe o valor total disponível para o período selecionado."
                placeholder="0,00"
                prefixo="R$"
                :erro="erros.orcamento"
                compacto
                @sair="formatarOrcamentoAoSair"
              />
            </div>
          </div>

          <div class="border-t border-[#eee2da] bg-[#fbf5f1] px-5 py-4">
            <p v-if="mensagemDoFormulario" class="mb-3 text-sm text-[#6b564a]" role="status">
              {{ mensagemDoFormulario }}
            </p>
            <button
              type="submit"
              :disabled="enviando"
              class="ml-auto flex h-10 w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-[#c2560b] px-5 text-sm font-medium text-white shadow-[0_8px_16px_-8px_rgba(157,68,0,0.8)] transition hover:-translate-y-px hover:bg-[#a54809] disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
            >
              {{ enviando ? 'Iniciando processamento…' : 'Continuar para revisão' }}
              <svg v-if="!enviando" class="size-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M3 8h9.5M9 4.5 12.5 8 9 11.5" />
              </svg>
            </button>
          </div>
        </form>
      </div>
    </main>
  </div>
</template>
