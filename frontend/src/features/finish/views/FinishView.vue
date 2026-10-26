<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { apiClient } from "@/services/api";
import type { JobResumo } from "@/types/api";
import { HttpError } from "@/services/http";
import { regraMaisRecente, simulacaoVisivel } from "@/services/job";
import { usarStoreJobAtual } from "@/stores/currentJob";
import TheProcessHeader from "@/components/TheProcessHeader.vue";
import TheSidebar from "@/components/TheSidebar.vue";
import CartaoRegra from "@/components/CartaoRegra.vue";
import RelatorioSimulacao from "@/components/RelatorioSimulacao.vue";
import { consultarDetalhamento } from "@/services/detalhamento";
import { useDetalhamento } from "@/composables/useDetalhamento";

const rota = useRoute();
const roteador = useRouter();
const store = usarStoreJobAtual();
const { job, carregando } = storeToRefs(store);
const jobId = computed(() => String(rota.params.id));
const quantidadeArquivadas = ref(0);
const quantidadeSalvas = ref(0);
const regra = computed(() =>
  job.value?.regras.find((item) => item.id === simulacao.value?.regra_id)
    ?? regraMaisRecente(job.value?.regras ?? []),
);
const simulacao = computed(() => simulacaoVisivel(job.value));
const regraDaSimulacao = computed(() =>
  job.value?.regras.find((item) => item.id === simulacao.value?.regra_id),
);
const identidadeRelatorio = computed(() => `${jobId.value}/${simulacao.value?.id ?? ''}`);
const relatorio = useDetalhamento(identidadeRelatorio, (signal) =>
  consultarDetalhamento(jobId.value, simulacao.value!.id, signal),
);
const { aberto: relatorioAberto, carregando: carregandoRelatorio, erro: erroRelatorio, resposta: detalhamento } = relatorio;
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

async function carregarContagensDeRegras(): Promise<void> {
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

    quantidadeArquivadas.value = resumosDosJobs.filter(
      (resumoDoJob) => resumoDoJob.status === "arquivado",
    ).length;

    quantidadeSalvas.value =
      resumosDosJobs.length - quantidadeArquivadas.value;
  } catch {
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
  void carregarContagensDeRegras();
});

onBeforeUnmount(() => {
  ciclo += 1;
  limparTemporizadores();
  store.pararAcompanhamento();
});
</script>

<template>
    <div v-if="alerta" class="fixed top-5 left-1/2 z-50 -translate-x-1/2 rounded-lg border-2 px-6 py-3 font-bold shadow-md" :class="alerta.tipo === 'sucesso' ? 'bg-green-50 border-green-300 text-green-700' : 'bg-red-50 border-red-300 text-red-700'">
      {{ alerta.mensagem }}
    </div>
    <div class="tela-de-negocio h-[100dvh] overflow-hidden bg-[#fdf7f3] text-[#2e1a10] lg:grid lg:h-[100dvh] lg:grid-cols-[16rem_minmax(0,1fr)] lg:overflow-hidden">
    <TheSidebar class="sticky top-0 hidden h-screen lg:flex" :quantidade-arquivadas="quantidadeArquivadas" :quantidade-salvas="quantidadeSalvas"/>
    <main class="flex h-full min-h-0 min-w-0 flex-col" :class="relatorioAberto ? 'overflow-y-auto' : 'overflow-hidden'">
    <TheProcessHeader etapa-da-rota="salvar" :status-do-job="job?.status ?? null" class="sticky top-0 z-20 mb-4 shrink-0" />
    <div class="flex w-full flex-col items-center px-4 pt-4 pb-4 font-['Tinos'] sm:px-6 sm:pt-6 sm:pb-6" :class="relatorioAberto ? 'shrink-0' : 'min-h-0 flex-1'">
        <div class="mb-8 shrink-0">
            <h1 class="mb-3 text-center text-3xl font-bold sm:text-3xl">Finalizar Regra</h1>
            <p class="text-center text-[#6b564a] text-base">Revise os detalhes da regra extraída e confirme o salvamento.</p>
        </div>
        <CartaoRegra
          class="mb-5 max-w-4xl" :class="relatorioAberto ? 'shrink-0' : 'min-h-0 flex-1'"
          :regra="regra" :simulacao="simulacao" :carregando="carregando" :erro="erroCarregamento"
        >
                <RelatorioSimulacao
                  v-if="!carregando && !erroCarregamento && simulacao?.status === 'sucesso'"
                  :aberto="relatorioAberto" :carregando="carregandoRelatorio" :erro="erroRelatorio"
                  :linhas="detalhamento?.linhas" :regra="regraDaSimulacao?.representacao"
                  :decomposicao="simulacao?.resultado?.decomposicao"
                  @alternar="relatorio.alternar" @tentar-novamente="relatorio.carregar"
                />
        </CartaoRegra>
        <div class="mb-0 flex shrink-0 flex-col items-stretch gap-3 sm:flex-row sm:items-center">
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
