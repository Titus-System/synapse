<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TheProcessHeader from '@/components/TheProcessHeader.vue'
import TheSidebar from '@/components/TheSidebar.vue'
import { apiClient } from '@/services/api'
import type { JobResumo } from '@/types/api'
import CampoDeMultiSelecao from '../components/CampoDeMultiSelecao.vue'
import CampoDeSelecao from '../components/CampoDeSelecao.vue'
import CampoDeTexto from '../components/CampoDeTexto.vue'
import { useFormularioRegra } from '../composables/useFormularioRegra'

const rota = useRoute()
const roteador = useRouter()
const quantidadeArquivadas = ref(0)
const quantidadeSalvas = ref(0)
const {
  opcoesDeCargo,
  opcoesDeLoja,
  opcoesDeMarca,
  opcoesDeVigencia,
  enviando,
  enviarFormulario,
  erros,
  formatarOrcamentoAoSair,
  formulario,
  limparFormulario,
  mensagemDoFormulario,
  preenchendo,
  preencherComRegraDoJob,
} = useFormularioRegra()

function atualizarContagensDeRegras(resumosDosJobs: readonly JobResumo[]): void {
  quantidadeArquivadas.value = resumosDosJobs.filter(
    (resumoDoJob) => resumoDoJob.status === 'arquivado',
  ).length
  quantidadeSalvas.value = resumosDosJobs.length - quantidadeArquivadas.value
}

async function carregarContagensDeRegras(): Promise<void> {
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

    atualizarContagensDeRegras(resumosDosJobs)
  } catch {
    quantidadeArquivadas.value = 0
    quantidadeSalvas.value = 0
  }
}

async function submeterFormulario(): Promise<void> {
  const jobCriado = await enviarFormulario()
  if (!jobCriado) return

  await carregarContagensDeRegras()

  const destino = roteador.resolve(`/jobs/${jobCriado.id}`)
  if (destino.name === 'not-found') {
    mensagemDoFormulario.value = 'Processamento iniciado. O acompanhamento será aberto em seguida.'
    return
  }

  await roteador.push(destino)
}

onMounted(() => {
  void carregarContagensDeRegras()
})

// A tela continua montada ao sair do reprocessamento pelo menu, e um formulário
// preenchido com a regra anterior não é o que "Nova regra" promete.
watch(
  () => rota.query.reprocessar,
  (jobParaReprocessar) => {
    if (typeof jobParaReprocessar === 'string' && jobParaReprocessar) {
      void preencherComRegraDoJob(jobParaReprocessar)
      return
    }

    limparFormulario()
  },
  { immediate: true },
)
</script>

<template>
  <div
    class="tela-de-negocio min-h-[100dvh] bg-[#fdf7f3] text-[#2e1a10] lg:grid lg:h-[100dvh] lg:grid-cols-[16rem_minmax(0,1fr)] lg:overflow-hidden"
  >
    <TheSidebar
      class="hidden lg:flex"
      :quantidade-arquivadas="quantidadeArquivadas"
      :quantidade-salvas="quantidadeSalvas"
    />

    <main
      class="flex min-w-0 flex-col bg-[radial-gradient(circle_at_top,#fffdfb_0%,#fdf7f3_48%,#f8eee8_100%)] lg:min-h-0 lg:overflow-y-auto"
    >
      <TheProcessHeader etapa-da-rota="voz-texto" />

      <div id="formulario-regra" class="mx-auto w-full max-w-[41.25rem] px-4 py-8 sm:px-6 lg:py-12">
        <header class="text-center">
          <h1
            class="font-serif text-3xl leading-tight font-semibold tracking-tight text-[#2e1a10] lg:text-4xl"
          >
            Capture uma Regra de Negócio
          </h1>
          <p class="mt-3 text-base text-[#6b564a]">
            Escreva os parâmetros da regra. Nós iremos estruturá-la para você.
          </p>
        </header>

        <form
          class="mx-auto mt-6 max-w-[33.75rem] rounded-xl border border-[#e7d6cb] bg-white shadow-[0_18px_45px_-24px_rgba(60,30,15,0.42)]"
          @submit.prevent="submeterFormulario"
        >
          <div
            class="grid grid-cols-1 gap-1 rounded-t-xl border-b border-[#eee2da] bg-[#f8f1ec] px-4 py-2.5 text-sm font-medium text-[#3a241a] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:gap-4 sm:px-5"
          >
            <span>Parâmetro</span>
            <span>Valor</span>
          </div>

          <div class="divide-y divide-[#eee2da]">
            <p class="px-5 py-3 text-sm text-[#6b564a]">
              Vigência opcional: se não informada, a regra vale para todo o período da simulação.
            </p>
            <div
              class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5"
            >
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
            <div
              class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5"
            >
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
            <div
              class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5"
            >
              <span class="text-sm">Loja</span>
              <CampoDeMultiSelecao
                v-if="!formulario.todasLojas"
                id="loja"
                v-model:valores="formulario.loja"
                rotulo="Loja"
                ajuda="Selecione uma ou mais lojas."
                resumo-plural="lojas selecionadas"
                :opcoes="opcoesDeLoja"
                :erro="erros.loja"
                compacto
              />
              <label class="flex items-center gap-2 text-sm sm:col-span-2"
                ><input v-model="formulario.todasLojas" type="checkbox" /> Vale para todas as
                lojas</label
              >
            </div>
            <div
              class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5"
            >
              <span class="text-sm">Marca</span>
              <CampoDeMultiSelecao
                v-if="!formulario.todasMarcas"
                id="marca"
                v-model:valores="formulario.marca"
                rotulo="Marca"
                ajuda="Selecione uma ou mais marcas."
                resumo-plural="marcas selecionadas"
                :opcoes="opcoesDeMarca"
                :erro="erros.marca"
                compacto
              />
              <label class="flex items-center gap-2 text-sm sm:col-span-2"
                ><input v-model="formulario.todasMarcas" type="checkbox" /> Vale para todas as
                marcas</label
              >
            </div>
            <div class="px-5 py-3">
              <label for="modo-taxa" class="mb-2 block text-sm">Comissionamento</label>
              <select
                id="modo-taxa"
                v-model="formulario.modoTaxa"
                class="w-full rounded-lg border border-[#e7d6cb] bg-white p-2 text-sm"
              >
                <option value="uniforme">Taxa uniforme para os cargos selecionados</option>
                <option value="porCargo">Taxas por cargo</option>
                <option value="uniformeComExcecoes">Taxa uniforme com exceções por cargo</option>
              </select>
            </div>
            <div v-if="formulario.modoTaxa !== 'uniforme'" class="space-y-3 px-5 py-3">
              <p class="text-sm">
                {{
                  formulario.modoTaxa === 'porCargo'
                    ? 'Informe cada cargo e sua taxa. Os demais cargos mantêm o baseline.'
                    : 'As taxas abaixo substituem a taxa uniforme somente nos cargos indicados.'
                }}
              </p>
              <div
                v-for="(taxa, indice) in formulario.taxasPorCargo"
                :key="indice"
                class="grid grid-cols-[1fr_1fr_auto] items-start gap-2"
              >
                <CampoDeSelecao
                  :id="`taxa-cargo-${indice}`"
                  v-model:valor="taxa.cargo"
                  :rotulo="`Cargo da taxa ${indice + 1}`"
                  :opcoes="opcoesDeCargo"
                  compacto
                />
                <CampoDeTexto
                  :id="`taxa-percentual-${indice}`"
                  v-model:valor="taxa.percentual"
                  :rotulo="`Percentual da taxa ${indice + 1}`"
                  sufixo="%"
                  placeholder="Ex.: 3"
                  compacto
                />
                <button
                  type="button"
                  class="p-2 text-sm text-[#a54809]"
                  :aria-label="`Remover taxa ${indice + 1}`"
                  @click="formulario.taxasPorCargo.splice(indice, 1)"
                >
                  Remover
                </button>
              </div>
              <p v-if="erros.taxasPorCargo" role="alert" class="text-sm text-red-700">
                {{ erros.taxasPorCargo }}
              </p>
              <button
                type="button"
                class="text-sm font-medium text-[#a54809]"
                @click="formulario.taxasPorCargo.push({ cargo: '', percentual: '' })"
              >
                Adicionar taxa por cargo
              </button>
            </div>
            <div
              class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5"
            >
              <span v-if="formulario.modoTaxa !== 'porCargo'" class="text-sm">Cargo</span>
              <CampoDeMultiSelecao
                v-if="formulario.modoTaxa !== 'porCargo' && !formulario.todosCargos"
                id="cargo"
                v-model:valores="formulario.cargo"
                rotulo="Cargo"
                ajuda="Selecione um ou mais cargos."
                resumo-plural="cargos selecionados"
                :opcoes="opcoesDeCargo"
                :erro="erros.cargo"
                compacto
              />
              <label
                v-if="formulario.modoTaxa !== 'porCargo'"
                class="flex items-center gap-2 text-sm sm:col-span-2"
                ><input v-model="formulario.todosCargos" type="checkbox" /> Vale para todos os
                cargos</label
              >
            </div>
            <div
              v-if="formulario.modoTaxa !== 'porCargo'"
              class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5"
            >
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
            <div
              class="grid grid-cols-1 gap-1 px-4 py-1.5 sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5"
            >
              <span class="text-sm">Meta de vendas</span>
              <CampoDeTexto
                id="meta-venda"
                v-model:valor="formulario.metaVenda"
                rotulo="Meta de vendas"
                ajuda="Informe a meta de vendas para o período da simulação."
                placeholder="0,00"
                prefixo="R$"
                :erro="erros.metaVenda"
                compacto
              />
            </div>
            <div
              class="grid grid-cols-1 gap-1 px-4 py-1.5 transition hover:bg-[#fdf9f6] sm:grid-cols-[minmax(0,1fr)_13.125rem] sm:items-center sm:gap-4 sm:px-5"
            >
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

          <div class="rounded-b-xl border-t border-[#eee2da] bg-[#fbf5f1] px-4 py-4 sm:px-5">
            <p v-if="mensagemDoFormulario" class="mb-3 text-sm text-[#6b564a]" role="status">
              {{ mensagemDoFormulario }}
            </p>
            <button
              type="submit"
              :disabled="enviando || preenchendo"
              class="ml-auto flex h-10 w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-[#c2560b] px-5 text-sm font-medium text-white shadow-[0_8px_16px_-8px_rgba(157,68,0,0.8)] transition hover:-translate-y-px hover:bg-[#a54809] disabled:cursor-not-allowed disabled:opacity-60 sm:w-auto"
            >
              {{ enviando ? 'Iniciando processamento…' : 'Continuar para revisão' }}
              <svg
                v-if="!enviando"
                class="size-4"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <path d="M3 8h9.5M9 4.5 12.5 8 9 11.5" />
              </svg>
            </button>
          </div>
        </form>
      </div>
    </main>
  </div>
</template>
