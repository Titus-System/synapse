<script setup lang="ts">
import {
  transformarRegra,
  transformarResultado,
} from "../composables/transformarRegra";
import { computed, onUnmounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { apiClient } from "@/services/api";
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
onUnmounted(() => {
  ciclo += 1;
  limparTemporizadores();
  store.pararAcompanhamento();
});
</script>

<template>
    <div v-if="alerta" class="fixed top-5 z-50 px-6 py-3 rounded-lg border-2 shadow-md font-bold" :class="alerta.tipo === 'sucesso' ? 'bg-green-50 border-green-300 text-green-700' : 'bg-red-50 border-red-300 text-red-700'">
      {{ alerta.mensagem }}
    </div>
    <div class="flex flex-row min-h-screen">
    <TheSidebar class="hidden md:flex w-[15.3%]"/>
    <div class="flex flex-col bg-[#fdf7f3] w-[84.7%] min-h-screen">
    <TheProcessHeader class="mb-12" />
    <div class="flex flex-col w-full justify-center items-center font-['Tinos']">
        <div class="mb-7">
            <h1 class="text-4xl font-bold text-center mb-3">Finalizar Regra</h1>
            <p class="text-center text-[#584237]">Revise os detalhes da regra extraída e confirme o salvamento.</p>
        </div>
        <div class="bg-white w-[70%] border-2 border-[#DFC0B2] rounded-xl flex flex-col mb-12">
            <div class=" pt-8 px-8 pb-4">
                <div>
                    <h2 class="font-bold text-2xl mb-2">{{ carregando ? 'Carregando regra...' : tituloRegra }}</h2>
                    <div class="flex flex-row gap-2">
                        <span v-if="!erroCarregamento" class="text-[#9D4400]">Extraída</span>
                        <template v-if="dataRegra">
                            <p class="text-[#9D4400]">•</p>
                            <span class="text-[#9D4400]">{{ dataRegra }}</span>
                        </template>
                    </div>
                    <div v-if="baixaRastreabilidade" class="mt-3 px-4 py-3 rounded-lg bg-[#fdf7f3] border border-[#FFDBCD] text-[#765B1A]">
                      <p class="font-bold mb-1">Baixa rastreabilidade</p>
                      <p class="text-sm">Não foi possível rastrear detalhadamente as decisões tomadas durante a simulação.</p>
                    </div>
                </div>
            </div>
            <hr class="self-center mb-4 border border-[#FFDBCD] w-[94%]">
            <div class="mx-8 mb-8 p-6 bg-[#FFF1EC] border border-[#FFDBCD] rounded-lg text-[#584237]">
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
                    <p class="text-[#584237]/70 font-bold">LÓGICA ESTRUTURADA (PRÉ-VISUALIZAÇÃO)</p>
                    <!-- SE -->
                    <div>
                      <h3 class="font-bold text-xl mb-3">SE</h3>

                      <div class="flex flex-col gap-2 pl-6">
                        <p v-for="(linha, indice) in regraFormatada.se" :key="`se-${indice}`">
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
                          ]" :key="`entao-${indice}`">{{ linha }}</p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
        <div class="flex flex-row items-center gap-4 mb-14">
            <button type="button" class="text-[#9D4400] px-9 py-3 rounded-lg border-2 border-[#9D4400] font-bold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed" :disabled="acaoProcessando !== null || carregando || erroCarregamento || !podeArquivar" @click="executarAcao('arquivar')">{{ acaoProcessando === 'arquivar' ? 'Processando...' : 'Arquivar' }}</button>
            <button type="button" class="bg-[#F47521] text-white font-bold px-9 py-3 rounded-lg cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed" :disabled="acaoProcessando !== null || carregando || erroCarregamento || !podeSalvar" @click="executarAcao('salvar')">{{ acaoProcessando === 'salvar' ? 'Processando...' : 'Salvar' }}</button>
        </div>
    </div>
    </div>
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