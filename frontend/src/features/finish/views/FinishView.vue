<script setup lang="ts">
import {
  transformarRegra,
  transformarResultado,
} from "../composables/transformarRegra";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { apiClient } from "@/services/api";
import type { JobResumo } from "@/types/api";
import { HttpError } from "@/services/http";
import { regraMaisRecente, simulacaoVisivel } from "@/services/job";
import { usarStoreJobAtual } from "@/stores/currentJob";
import TheProcessHeader from "@/components/TheProcessHeader.vue";
import TheSidebar from "@/components/TheSidebar.vue";

const rota = useRoute();
const roteador = useRouter();
const store = usarStoreJobAtual();
const { job, carregando } = storeToRefs(store);
const jobId = computed(() => String(rota.params.id));
const regrasRecentes = ref<{ identificador: string; rotulo: string }[]>([]);
const quantidadeArquivadas = ref(0);
const quantidadeSalvas = ref(0);
const regra = computed(() => regraMaisRecente(job.value?.regras ?? []));
const simulacao = computed(() => simulacaoVisivel(job.value));
const erroCarregamento = computed(() => store.erro !== null);
const acaoProcessando = ref<"salvar" | "arquivar" | null>(null);
const alerta = ref<{ tipo: "sucesso" | "erro"; mensagem: string } | null>(null);
const podeSalvar = computed(
  () => job.value?.status === "aguardando_decisao_usuario",
);
const podeArquivar = computed(() =>
  ["aguardando_decisao_usuario", "simulacao_inviavel"].includes(
    job.value?.status ?? "",
  ),
);
let temporizadorAlerta: ReturnType<typeof setTimeout> | null = null;
let temporizadorNavegacao: ReturnType<typeof setTimeout> | null = null;
let ciclo = 0;

function criarRotuloDaRegra(resumoDoJob: JobResumo): string {
  const data = new Date(resumoDoJob.criado_em).toLocaleDateString("pt-BR");
  return `Regra · ${data}`;
}

function limparTemporizadores() {
  if (temporizadorAlerta) clearTimeout(temporizadorAlerta);
  if (temporizadorNavegacao) clearTimeout(temporizadorNavegacao);
}

function exibirAlerta(tipo: "sucesso" | "erro", mensagem: string) {
  if (temporizadorAlerta) clearTimeout(temporizadorAlerta);
  alerta.value = { tipo, mensagem };
  temporizadorAlerta = setTimeout(() => {
    alerta.value = null;
  }, 4000);
}

async function carregarRegrasRecentes(): Promise<void> {
  try {
    const resumosDosJobs: JobResumo[] = [];
    let numeroDaPagina = 0;
    let totalDeJobs = 0;
    let itensDaPagina: JobResumo[] = [];

    do {
      const paginaDeJobs = await apiClient.listarJobs({
        pagina: numeroDaPagina,
        tamanho: 100,
      });

      totalDeJobs = paginaDeJobs.total;
      itensDaPagina = paginaDeJobs.itens;
      resumosDosJobs.push(...itensDaPagina);
      numeroDaPagina += 1;
    } while (
      resumosDosJobs.length < totalDeJobs &&
      itensDaPagina.length > 0
    );

    regrasRecentes.value = resumosDosJobs.slice(0, 6).map((resumoDoJob) => ({
      identificador: resumoDoJob.id,
      rotulo: criarRotuloDaRegra(resumoDoJob),
    }));

    quantidadeArquivadas.value = resumosDosJobs.filter(
      (resumoDoJob) => resumoDoJob.status === "arquivado",
    ).length;

    quantidadeSalvas.value =
      resumosDosJobs.length - quantidadeArquivadas.value;
  } catch {
    regrasRecentes.value = [];
    quantidadeArquivadas.value = 0;
    quantidadeSalvas.value = 0;
  }
}

async function executarAcao(acao: "salvar" | "arquivar"): Promise<void> {
  if (
    !job.value ||
    acaoProcessando.value ||
    carregando.value ||
    erroCarregamento.value
  )
    return;
  if (acao === "salvar" ? !podeSalvar.value : !podeArquivar.value) return;
  const atual = ciclo;
  const id = job.value.id;
  acaoProcessando.value = acao;
  alerta.value = null;
  try {
    const atualizado = await apiClient.executarAcao(id, { acao });
    if (atual !== ciclo) return;
    store.aplicarJob(atualizado);
    exibirAlerta(
      "sucesso",
      acao === "salvar"
        ? "Regra salva com sucesso!"
        : "Regra arquivada com sucesso!",
    );
    temporizadorNavegacao = setTimeout(() => {
      if (atual === ciclo) void roteador.push("/nova-regra");
    }, 1200);
  } catch (falha) {
    if (atual !== ciclo) return;
    exibirAlerta(
      "erro",
      falha instanceof HttpError
        ? falha.message
        : "Não foi possível concluir a ação. Tente novamente.",
    );
    if (falha instanceof HttpError && falha.status === 409)
      await store.consultarJob();
  } finally {
    if (atual === ciclo) acaoProcessando.value = null;
  }
}

const dataRegra = computed(() =>
  regra.value
    ? new Date(regra.value.criada_em).toLocaleString("pt-BR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "",
);
const baixaRastreabilidade = computed(
  () => simulacao.value?.flag_baixa_rastreabilidade === true,
);
const tituloRegra = computed(() =>
  regra.value ? `Regra ${regra.value.id.slice(0, 6)}` : "Nova Regra",
);
const regraFormatada = computed(() =>
  regra.value
    ? transformarRegra(regra.value.representacao)
    : { se: [], entao: [] },
);
const resultadoFormatado = computed(() =>
  simulacao.value?.status === "sucesso" && simulacao.value.resultado
    ? transformarResultado(simulacao.value.resultado)
    : [],
);

watch(
  jobId,
  () => {
    ciclo += 1;
    limparTemporizadores();
    acaoProcessando.value = null;
    alerta.value = null;
    void store.iniciarAcompanhamento(jobId.value);
  },
  { immediate: true },
);

onMounted(() => {
  void carregarRegrasRecentes();
});

onUnmounted(() => {
  ciclo += 1;
  limparTemporizadores();
  store.pararAcompanhamento();
});
</script>

<template>
    <div v-if="alerta" class="fixed top-5 left-1/2 z-50 -translate-x-1/2 rounded-lg border-2 px-6 py-3 font-bold shadow-md" :class="alerta.tipo === 'sucesso' ? 'bg-green-50 border-green-300 text-green-700' : 'bg-red-50 border-red-300 text-red-700'">
      {{ alerta.mensagem }}
    </div>
    <div class="tela-de-negocio min-h-[100dvh] bg-[#fdf7f3] text-[#2e1a10] lg:grid lg:h-[100dvh] lg:grid-cols-[16rem_minmax(0,1fr)] lg:overflow-hidden">
    <TheSidebar class="sticky top-0 hidden h-screen lg:flex" :quantidade-arquivadas="quantidadeArquivadas" :quantidade-salvas="quantidadeSalvas" :regras-recentes="regrasRecentes"/>
    <main class="min-w-0 lg:min-h-0 lg:overflow-y-auto">
    <TheProcessHeader etapa-da-rota="salvar" :status-do-job="job?.status ?? null" class="mb-12 sticky top-0" />
    <div class="flex w-full flex-col items-center justify-center px-4 font-['Tinos'] sm:px-6">
        <div class="mb-7">
            <h1 class="mb-3 text-center text-3xl font-bold sm:text-3xl">Finalizar Regra</h1>
            <p class="text-center text-[#6b564a] text-base">Revise os detalhes da regra extraída e confirme o salvamento.</p>
        </div>
        <div class="mb-12 flex w-3xl max-w-4xl flex-col rounded-xl border-2 border-[#DFC0B2] bg-white">
            <div class="px-4 pt-8 pb-4 sm:px-8">
                <div>
                    <h2 class="font-bold text-2xl mb-2">{{ carregando ? 'Carregando regra...' : tituloRegra }}</h2>
                    <div class="flex flex-row gap-2">
                        <span v-if="!erroCarregamento" class="text-[#9D4400] text-sm">Extraída</span>
                        <template v-if="dataRegra">
                            <p class="text-[#9D4400] text-sm">•</p>
                            <span class="text-[#9D4400] text-sm">{{ dataRegra }}</span>
                        </template>
                    </div>
                    <div v-if="baixaRastreabilidade" class="mt-3 px-4 py-3 rounded-lg bg-[#fdf7f3] border border-[#FFDBCD] text-[#765B1A]">
                      <p class="font-bold mb-1">Baixa rastreabilidade</p>
                      <p class="text-sm">Não foi possível rastrear detalhadamente as decisões tomadas durante a simulação.</p>
                    </div>
                </div>
            </div>
            <hr class="self-center mb-4 border border-[#FFDBCD] w-[94%]">
            <div class="mx-4 mb-8 rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-4 text-[#584237] sm:mx-8 sm:p-6">
                <div v-if="carregando" class="flex flex-col items-center justify-center py-8 gap-3">
                    <div class="w-7 h-7 border-4 border-[#FFDBCD] border-t-[#F47521] rounded-full animate-spin"></div>
                        <p class="text-[#584237]">Carregando dados da regra...</p>
                </div>
                <div v-else-if="erroCarregamento" class="flex flex-col items-center justify-center text-center py-10 px-6 gap-3">
                  <div class="w-12 h-12 flex items-center justify-center rounded-full bg-[#ffc1b0] text-[#950606] text-2xl font-bold">!</div>
                    <h3 class="font-bold text-2xl text-[rgb(149,6,6)]">Um erro impossibilitou o carregamento da regra.</h3>
                    <p class="text-lg text-[#950606]"> Por favor, tente novamente.</p>
                  </div>
                  <div v-else class="flex flex-col gap-8">
                    <p class="text-[#584237]/70 font-bold text-xl">LÓGICA ESTRUTURADA (PRÉ-VISUALIZAÇÃO)</p>
                    <!-- SE -->
                    <div>
                      <h3 class="font-bold text-xl mb-3">SE</h3>

                      <div class="flex flex-col gap-1 pl-6">
                        <p v-for="(linha, indice) in regraFormatada.se" :key="`se-${indice}`" class='text-sm'>
                          {{ linha }}
                        </p>
                      </div>
                    </div>

                    <!-- ENTÃO -->
                    <div>
                      <h3 class="font-bold text-xl mb-3">ENTÃO</h3>
                      <div class="flex flex-col gap-2 pl-6">
                        <p v-for="(linha, indice) in [
                            ...regraFormatada.entao,
                            ...resultadoFormatado,
                          ]" :key="`entao-${indice}`" class='text-sm'>{{ linha }}</p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
        <div class="mb-14 flex flex-col items-stretch gap-4 sm:flex-row sm:items-center">
            <button type="button" class="text-[#9D4400] px-9 py-3 rounded-lg border-2 border-[#9D4400] font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed" :disabled="acaoProcessando !== null || carregando || erroCarregamento || !podeArquivar" @click="executarAcao('arquivar')">{{ acaoProcessando === 'arquivar' ? 'Processando...' : 'Arquivar' }}</button>
            <button type="button" class="bg-[#F47521] text-white font-bold px-9 py-3 rounded-lg cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed" :disabled="acaoProcessando !== null || carregando || erroCarregamento || !podeSalvar" @click="executarAcao('salvar')">{{ acaoProcessando === 'salvar' ? 'Processando...' : 'Salvar' }}</button>
        </div>
    </div>
    </main>
    </div>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Tinos:ital,wght@0,400;0,700;1,400;1,700&display=swap');

input,
button,
textarea,
select {
  font-family: inherit;
}
</style>
