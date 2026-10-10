<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { apiClient } from '@/services/api'
import type { JobResumo } from '@/types/api'
import TheProcessHeader from '@/components/TheProcessHeader.vue'
import TheSidebar from '@/components/TheSidebar.vue'

import EntradaTexto from '../components/EntradaTexto.vue'
import EntradaVoz from '../components/EntradaVoz.vue'

const modo = ref<'voz' | 'texto'>('voz')
const descricao = ref('')
const regrasRecentes = ref<{ identificador: string; rotulo: string }[]>([])
const quantidadeArquivadas = ref(0)
const quantidadeSalvas = ref(0)
const carregandoHistorico = ref(true)
const erroHistorico = ref(false)
const controlador = new AbortController()

async function carregarHistorico() {
  if (controlador.signal.aborted) return
  carregandoHistorico.value = true
  erroHistorico.value = false
  const inicio = performance.now()
  let resultado = 'sucesso'
  try {
    const jobs: JobResumo[] = []
    let pagina = 0
    let total = 0
    do {
      const resposta = await apiClient.listarJobs({ pagina, tamanho: 100 }, controlador.signal)
      if (controlador.signal.aborted) return
      jobs.push(...resposta.itens)
      total = resposta.total
      pagina += 1
      if (!resposta.itens.length) break
    } while (jobs.length < total)
    regrasRecentes.value = jobs.slice(0, 6).map((job) => ({
      identificador: job.id,
      rotulo: `Regra · ${new Date(job.criado_em).toLocaleDateString('pt-BR')}`,
    }))
    quantidadeArquivadas.value = jobs.filter((job) => job.status === 'arquivado').length
    quantidadeSalvas.value = jobs.length - quantidadeArquivadas.value
  } catch {
    if (controlador.signal.aborted) return
    resultado = 'falha'
    erroHistorico.value = true
  } finally {
    if (!controlador.signal.aborted) {
      carregandoHistorico.value = false
      const registro = JSON.stringify({
        timestamp: new Date().toISOString(),
        level: resultado === 'sucesso' ? 'INFO' : 'ERROR',
        message: 'Consulta do resumo de regras concluída',
        'service.name': 'synapse-frontend',
        extra: { operacao: 'listar_regras', resultado, duracao_ms: performance.now() - inicio },
      })
      if (resultado === 'sucesso') console.info(registro)
      else console.error(registro)
    }
  }
}
onMounted(carregarHistorico)
onBeforeUnmount(() => controlador.abort())
</script>

<template>
  <div
    class="h-[100dvh] overflow-hidden bg-[#fffaf7] font-sans text-[#584237] lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]"
  >
    <TheSidebar
      v-if="!carregandoHistorico && !erroHistorico"
      class="sticky top-0 hidden h-screen lg:flex"
      :regras-recentes="regrasRecentes"
      :quantidade-salvas="quantidadeSalvas"
      :quantidade-arquivadas="quantidadeArquivadas"
    />
    <aside
      v-else
      class="sticky top-0 hidden h-screen flex-col bg-[#3b2318] p-5 text-[#f6eae3] lg:flex"
    >
      <span class="font-serif text-xl font-bold">Synapse</span>
      <RouterLink
        to="/nova-regra"
        class="mt-6 rounded-lg bg-[#f26b0f] px-4 py-3 text-center text-sm"
        >Nova Regra</RouterLink
      >
      <p v-if="carregandoHistorico" role="status" class="mt-5 text-sm">Carregando histórico...</p>
      <div v-else role="alert" class="mt-5 text-sm">
        <p>Não foi possível carregar o histórico.</p>
        <button type="button" class="mt-3 underline" @click="carregarHistorico">
          Tentar novamente
        </button>
      </div>
    </aside>
    <main class="flex h-full min-h-0 min-w-0 flex-col">
      <TheProcessHeader etapa-da-rota="voz-texto" class="shrink-0" />
      <div class="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-5 py-6 sm:px-8">
        <section class="my-auto w-full max-w-4xl shrink-0 text-center">
          <h1 class="font-serif text-3xl leading-tight text-[#321f16] sm:text-4xl lg:text-5xl">
            Capture uma Regra de Negócio
          </h1>
          <p class="mx-auto mt-5 max-w-xl text-base leading-relaxed text-[#7b6559] sm:text-lg">
            Fale ou escreva sobre a regra. Nossa IA irá estruturá-la para você.
          </p>
          <div
            class="mx-auto mt-8 flex w-fit rounded-full border border-[#f3d9ce] bg-[#ffebe3] p-1"
            role="group"
            aria-label="Forma de entrada"
          >
            <button
              type="button"
              :aria-pressed="modo === 'voz'"
              class="flex min-w-28 items-center justify-center gap-2 rounded-full px-5 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-[#b65108]"
              :class="modo === 'voz' ? 'bg-white text-[#b65108] shadow-sm' : 'text-[#7b6559]'"
              @click="modo = 'voz'"
            >
              <svg
                class="size-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                aria-hidden="true"
              >
                <rect x="9" y="2" width="6" height="13" rx="3" />
                <path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3" /></svg
              >Voz
            </button>
            <button
              type="button"
              :aria-pressed="modo === 'texto'"
              class="flex min-w-28 items-center justify-center gap-2 rounded-full px-5 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-[#b65108]"
              :class="modo === 'texto' ? 'bg-white text-[#b65108] shadow-sm' : 'text-[#7b6559]'"
              @click="modo = 'texto'"
            >
              <span aria-hidden="true" class="font-serif text-lg font-bold">Tt</span>Texto
            </button>
          </div>
          <div class="mt-10 sm:mt-14">
            <EntradaVoz v-if="modo === 'voz'" />
            <EntradaTexto v-else v-model="descricao" />
          </div>
          <p class="mt-6 text-xs text-[#9d8274]">
            Prévia visual. A gravação e o envio ainda não estão disponíveis.
          </p>
        </section>
      </div>
    </main>
  </div>
</template>
