<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { apiClient } from "@/services/api";
import type { JobResumo } from "@/types/api";
import { useRoute, useRouter } from "vue-router";
import { useJobSimulacao } from "../composables/useJobSimulacao";
import TheProcessHeader from "@/components/TheProcessHeader.vue";
import TheSidebar from "@/components/TheSidebar.vue";

const rota = useRoute();
const roteador = useRouter();
const jobId = computed(() => String(rota.params.id));
const regrasRecentes = ref<{ identificador: string; rotulo: string }[]>([]);
const quantidadeArquivadas = ref(0);
const quantidadeSalvas = ref(0);

const {
  job,
  carregando,
  erro,
  erroEspecifico,
  iniciar,
  parar,
  regra,
  sugestao,
  simulacao,
  aguardandoConfirmacao,
  aceitarSugestao,
  cancelar,
  podeAceitarSugestao,
  podeCancelar,
  podeFinalizar,
} = useJobSimulacao(jobId);


const nucleo = computed(() => regra.value?.representacao.nucleo);

function criarRotuloDaRegra(resumoDoJob: JobResumo): string {
  const data = new Date(resumoDoJob.criado_em).toLocaleDateString("pt-BR");
  return `Regra · ${data}`;
}

function seguirParaFinalizacao(): void {
  if (!podeFinalizar.value) return;
  roteador.push({
    name: "finalizar",
    params: {
      id: rota.params.id,
    },
  });
}

async function cancelarFluxo(): Promise<void> {
  if (await cancelar()) await roteador.push("/nova-regra");
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

function formatarCompetencia(valor: string): string {
  const [ano, mes] = valor.split("-");

  if (!ano || !mes) return valor;

  return `${mes}/${ano}`;
}

const vigencia = computed(() => {
  const valor = nucleo.value?.vigencia;

  if (!valor) return "";

  const inicio = formatarCompetencia(valor.inicio);
  const fim = formatarCompetencia(valor.fim);

  if (valor.inicio === valor.fim) {
    return inicio;
  }

  return `${inicio} até ${fim}`;
});

const loja = computed(() => nucleo.value?.loja?.join(", ") ?? "");

const marca = computed(() => nucleo.value?.marca?.join(", ") ?? "");

const cargo = computed(() => nucleo.value?.cargo?.join(", ") ?? "");

const meta = computed(() => {
  const valor = job.value?.orcamento;

  if (valor == null) return "";

  return `R$ ${valor.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
});

const percentual = computed(() => {
  const valor = nucleo.value?.percentual;

  if (valor == null) return "";

  return new Intl.NumberFormat("pt-BR", {
    style: "percent",
    maximumFractionDigits: 4,
  }).format(valor);
});

const totalComissionamento = computed(() => {
  const valor = simulacao.value?.resultado?.totais?.simulado;

  if (valor == null) return "";

  return `R$ ${valor.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
});

const orcamentoExcedido = computed(() => {
  const simulado = simulacao.value?.resultado?.totais?.simulado;
  const orcamento = simulacao.value?.resultado?.totais?.orcamento;

  if (simulado == null || orcamento == null || simulado <= orcamento) {
    return "";
  }

  const excedente = simulado - orcamento;

  return `R$ ${excedente.toLocaleString("pt-BR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
});

const regraViavel = computed(() => simulacao.value?.veredito === "viavel");

const regraInviavel = computed(() => simulacao.value?.veredito === "inviavel");

const assercaoViolada = computed(
  () => simulacao.value?.status === "assercao_violada",
);

watch(
  jobId,
  () => {
    void iniciar();
  },
  { immediate: true },
);
onMounted(() => {
  void carregarRegrasRecentes();
});

onUnmounted(parar);
</script>

<template>
    <div class="font-['Tinos'] bg-[#fffaf7]">
    <div class="flex flex-row min-h-screen">
    <TheSidebar class="hidden md:flex" :quantidade-arquivadas="quantidadeArquivadas" :quantidade-salvas="quantidadeSalvas" :regras-recentes="regrasRecentes"/>
    <div class="flex flex-col min-h-screen w-[84.7%]">
    <TheProcessHeader class="mb-12" />
    <!-- Simulação -->
        <div class="mb-12 p-10">
            <div class="mb-11">
                <h1 class="text-3xl text-[#2B160D] mb-2 font-semibold">Simulação</h1>
                <div v-if="carregando">
                    <p class="text-[#584237] font-bold">Carregando processamento...</p>
                </div>
                <div v-else-if="erro">
                    <p class="text-[#584237] font-bold">Ocorreu um problema ao carregar esta simulação.</p>
                </div>
                <div v-else>
                    <p class="text-[#584237]">Verifique a viabilidade da sua regra de negócio.</p>
                </div>
            </div>
            <div>
                <div v-if="erro" class="flex flex-col items-center justify-center py-16">
                    <font-awesome-icon :icon="['fas', 'circle-exclamation']" class="text-5xl text-[#950606] mb-4"/>
                    <h2 class="text-2xl text-[#950606] font-bold mb-2">Não foi possível carregar a simulação</h2>
                    <p v-if="erroEspecifico" class="text-[#584237] text-center max-w-xl">
                        {{ erro }}
                    </p>
                    <p v-else class="text-[#584237] text-center max-w-xl">
                        Por favor, tente novamente.
                    </p>
                                </div>
                <div v-else class="flex flex-row">
                    <div class="w-[50%]">
                        <h3 class="font-bold">Regra estruturada</h3>
                        <hr class="mb-4 border border-[#FFDBCD] w-[89%]">
                            <form class="flex flex-row gap-22">
                                <div class="flex flex-col">
                                    <div class="flex flex-col">
                                        <label for="vigencia" class="mb-1 text-[#584237]">Vigência</label>
                                        <input id="vigencia" type="text" :value="vigencia" readonly :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : regraInviavel ? 'text-[#950606]' : 'text-[#2B160D]'
    ]"/>
                                    </div>
                                    <div class="flex flex-col">
                                        <label for="loja" class="mb-1 text-[#584237]">Loja</label>
                                        <input id="loja" type="text" :value="loja" readonly :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : regraInviavel ? 'text-[#950606]' : 'text-[#2B160D]'
    ]"/>
                                    </div>

                                    <div class="flex flex-col">
                                        <label for="marca" class="mb-1 text-[#584237]">Marca</label>
                                        <input id="marca" type="text" :value="marca" readonly :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : regraInviavel ? 'text-[#950606]' : 'text-[#2B160D]'
    ]" />
                                    </div>
                                </div>
                                <div class="flex flex-col">
                                    <label for="cargo" class="mb-1 text-[#584237]">Cargo</label>
                                    <input id="cargo" type="text" :value="cargo" readonly :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : regraInviavel ? 'text-[#950606]' : 'text-[#2B160D]'
    ]"/>

                                    <label for="meta" class="mb-1 text-[#584237]">Meta</label>
                                    <input id="meta" type="text" :value="meta" readonly :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : regraInviavel ? 'text-[#950606]' : 'text-[#2B160D]'
    ]"/>

                                    <label for="percentual" class="mb-1 text-[#584237]">Percentual</label>
                                    <input id="percentual" type="text" :value="percentual" readonly :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : regraInviavel ? 'text-[#950606]' : 'text-[#2B160D]'
    ]"/>
                                </div>
                            </form>
                    </div>
                    <div class="border-2 border-[#DFC0B2] rounded-lg w-[50%] p-5">
                        <h3 class="font-bold">Dados da simulação</h3>
                        <hr class="mb-4 border border-[#FFDBCD]">
                        <div class="flex flex-col mb-8">
                            <label for="totalComissionamento" class="mb-1 text-[#584237]">Total de comissionamento</label>
                            <input id="totalComissionamento" type="text" :value="totalComissionamento" readonly placeholder="R$ X,00"  class="bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265] text-[#2B160D] px-3.5 py-3 w-full"/>
                        </div>
                        <!-- Aprovada -->
                        <div v-if="regraViavel" class="flex flex-col w-[80%] rounded-lg mb-3 border-l-8 border-r border-t border-b border-l-[#14532D] border-r-[#14532D]/20 border-t-[#14532D]/20 border-b-[#14532D]/20 bg-[#F4ECE6]/50 p-3">
                            <div class="flex flex-row items-center gap-3.5">
                                <font-awesome-icon
                                    :icon="['far', 'circle-check']"
                                    class="text-2xl text-[#14532D]"
                                />
                                <div class="flex flex-col">
                                    <h4 class="text-[#14532D] mb-1 font-bold">Resultado: Regra de negócio aprovada!</h4>
                                    <ul class="list-disc list-inside">
                                        <li class="text-[#584237]">A regra de negócio cabe no seu orçamento.</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                        <button
                                v-if="regraViavel && podeFinalizar"
                                type="button"
                                class="flex items-center justify-center cursor-pointer rounded-lg bg-[#14532D] text-white px-6 py-3 mt-4"
                                @click="seguirParaFinalizacao"
                            >
                                Seguir para Finalização
                            </button>
                        <!-- Reprovada -->
                        <div v-if="regraInviavel" class="flex flex-col w-[80%] rounded-lg mb-3 border-l-8 border-r border-t border-b border-l-[#950606] border-r-[#950606]/20 border-t-[#950606]/20 border-b-[#950606]/20 bg-[#F4ECE6]/50 p-3">
                            <div class="flex flex-row items-center gap-3.5">
                                <font-awesome-icon
                                    :icon="['far', 'circle-xmark']"
                                    class="text-2xl text-[#950606]"
                                />
                                <div class="flex flex-col">
                                    <h4 class="text-[#950606] mb-1 font-bold">Resultado: Regra de negócio reprovada!</h4>
                                    <ul class="list-disc list-inside">
                                        <li class="text-[#584237]">A regra de negócio NÃO cabe no seu orçamento.</li>
                                        <li class="text-[#584237]">O orçamento foi excedido em <span class="text-[#950606] font-bold">{{ orcamentoExcedido }}</span>.</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                        <!-- Erro: asserção violada -->
                        <div
                            v-if="assercaoViolada"
                            class="flex flex-col w-[80%] rounded-lg mb-3 border-l-8 border-r border-t border-b border-l-[#B45309] border-r-[#B45309]/20 border-t-[#B45309]/20 border-b-[#B45309]/20 bg-[#F4ECE6]/50 p-3"
                        >
                            <div class="flex flex-row items-center gap-3.5">
                                <font-awesome-icon
                                    :icon="['fas', 'circle-exclamation']"
                                    class="text-2xl text-[#B45309]"
                                />

                                <div class="flex flex-col">
                                    <h4 class="text-[#B45309] mb-1 font-bold">
                                        Erro: não foi possível concluir a simulação.
                                    </h4>

                                    <ul class="list-disc list-inside">
                                        <li class="text-[#584237]">
                                            Uma das condições necessárias para validar a regra de negócio não foi atendida.
                                        </li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    <!-- Sugestão (tornar aparição dinâmica depois) -->
        <div v-if="sugestao && (regraInviavel || aguardandoConfirmacao)" class="mb-8 p-10">
            <div class="mb-11">
                <h1 class="text-3xl text-[#2B160D] mb-2 font-semibold">Sugestão</h1>
                <p class="text-[#584237]">A regra de negócio escolhida é inviável. Mas não se preocupe, criamos esta para você:</p>
            </div>
            <div>
                <div class="flex flex-row">
                    <div class="w-[50%]">
                        <h3 class="font-bold">Regra estruturada</h3>
                        <hr class="mb-4 border border-[#FFDBCD] w-[89%]">
                            <form class="flex flex-row gap-22">
                                <div class="flex flex-col">
                                    <div class="flex flex-col">
                                        <label for="vigencia" class="mb-1 text-[#584237]">Vigência</label>
                                        <input id="vigencia" type="text" readonly :value="vigencia" :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : 'text-[#2B160D]'
    ]"/>
                                    </div>
                                    <div class="flex flex-col">
                                        <label for="loja" class="mb-1 text-[#584237]">Loja</label>
                                        <input id="loja" type="text" readonly :value="sugestao?.representacao.nucleo.loja?.join(', ') ?? ''" :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : 'text-[#2B160D]'
    ]"/>
                                    </div>

                                    <div class="flex flex-col">
                                        <label for="marca" class="mb-1 text-[#584237]">Marca</label>
                                        <input id="marca" type="text" readonly :value="sugestao?.representacao.nucleo.marca?.join(', ') ?? ''" :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : 'text-[#2B160D]'
    ]" />
                                    </div>
                                </div>
                                <div class="flex flex-col">
                                    <label for="cargo" class="mb-1 text-[#584237]">Cargo</label>
                                    <input id="cargo" type="text" readonly :value="sugestao?.representacao.nucleo.cargo?.join(', ') ?? ''" :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : 'text-[#2B160D]'
    ]"/>

                                    <label for="meta" class="mb-1 text-[#584237]">Meta</label>
                                    <input id="meta" type="text" readonly :value="meta" :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : 'text-[#2B160D]'
    ]"/>

                                    <label for="percentual" class="mb-1 text-[#584237]">Percentual</label>
                                    <input id="percentual" type="text" readonly :value="sugestao?.representacao.nucleo.percentual == null ? '' : new Intl.NumberFormat('pt-BR', { style: 'percent', maximumFractionDigits: 4 }).format(sugestao.representacao.nucleo.percentual)" :class="[
        'bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]',
        assercaoViolada ? 'text-[#B45309]' : 'text-[#2B160D]'
    ]"/>
                                </div>
                            </form>
                    </div>
                    <div class="border-2 border-[#DFC0B2] rounded-lg w-[50%] p-5">
                        <h3 class="font-bold">Dados da simulação</h3>
                        <hr class="mb-4 border border-[#FFDBCD]">
                        <div class="flex flex-col mb-8">
                            <label for="percentual" class="mb-1 text-[#584237]">Total de comissionamento</label>
                            <input id="percentual" type="text" readonly placeholder="R$ X,00"  class="bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265] text-[#2B160D] px-3.5 py-3 w-full"/>
                        </div>
                        <p class="text-lg mb-3">Deseja escolher essa nova regra?</p>
                        <div class="flex flex-row justify-around p-0 mb-3 gap-16">
                            <!-- SIM -->
                            <button type="button" :disabled="!podeAceitarSugestao" @click="aceitarSugestao" class="flex flex-col w-[50%] cursor-pointer h-fit rounded-lg border-l-8 border-r border-t border-b border-l-[#14532D] border-r-#14532D]/20 border-t-[#14532D]/20 border-b-[#14532D]/20 bg-[#F4ECE6]/50 p-3 items-center justify-center">
                                <div class="flex flex-col items-center">
                                    <h4 class="text-[#14532D] font-bold">SIM!</h4>
                                    <span class="text-[#584237]">Seguir para a próxima etapa.</span>
                                </div>
                            </button>
                            <!-- NÃO -->
                            <button type="button" class="flex flex-col w-[50%] h-fit cursor-pointer rounded-lg border-l-8 border-r border-t border-b border-l-[#950606] border-r-[#950606]/20 border-t-[#950606]/20 border-b-[#950606]/20 bg-[#F4ECE6]/50 p-3 items-center justify-center" :disabled="!podeCancelar" @click="cancelarFluxo">
                                <div class="flex flex-col items-center">
                                    <h4 class="text-[#950606] font-bold">Não.</h4>
                                    <span class="text-[#584237]">Cancelar este fluxo.</span>
                                </div>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
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