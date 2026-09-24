<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import TheProcessHeader from '@/components/TheProcessHeader.vue'
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
  <div class="tela-de-negocio min-h-[100dvh] bg-[#fdf7f3] text-[#2e1a10] lg:grid lg:h-[100dvh] lg:grid-cols-[16rem_minmax(0,1fr)] lg:overflow-hidden">
    <TheSidebar
      class="hidden lg:flex"
      :quantidade-arquivadas="quantidadeArquivadas"
      :quantidade-salvas="quantidadeSalvas"
      :regras-recentes="regrasRecentes"
    />

    <main class="flex min-w-0 flex-col bg-[radial-gradient(circle_at_top,#fffdfb_0%,#fdf7f3_48%,#f8eee8_100%)] lg:min-h-0 lg:overflow-y-auto">
      <TheProcessHeader etapa-da-rota="voz-texto" />

      <div id="formulario-regra" class="mx-auto w-full max-w-[41.25rem] px-4 py-8 sm:px-6 lg:py-12">
        <header class="text-center">
          <h1 class="font-serif text-3xl leading-tight font-semibold tracking-tight text-[#2e1a10] lg:text-4xl">
            Capture uma Regra de Negócio
          </h1>
          <p class="mt-3 text-base text-[#6b564a]">Escreva os parâmetros da regra. Nós iremos estruturá-la para você.</p>
        </header>

        <form
          class="mx-auto mt-6 max-w-[33.75rem] overflow-hidden rounded-xl border border-[#e7d6cb] bg-white shadow-[0_18px_45px_-24px_rgba(60,30,15,0.42)]"
          @submit.prevent="submeterFormulario"
        >
          <div
            class="grid grid-cols-1 gap-1 border-b border-[#eee2da] bg-[#f8f1ec] px-4 py-2.5 text-sm font-medium text-[#3a241a] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:gap-4 sm:px-5"
          >
            <span>Parâmetro</span>
            <span>Valor</span>
          </div>

          <div class="divide-y divide-[#eee2da]">
            <div class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5">
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
            <div class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5">
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
            <div class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5">
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
            <div class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5">
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
            <div class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5">
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
            <div class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5">
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
            <div class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5">
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

          <div class="border-t border-[#eee2da] bg-[#fbf5f1] px-4 py-4 sm:px-5">
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
