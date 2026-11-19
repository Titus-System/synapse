<script setup lang="ts">
import { computed } from 'vue'
import { transformarRegra } from '@/composables/transformarRegra'
import { dataAuditoria } from '../composables/apresentacaoAuditoria'
import type { AudiosEntradas, RegistroAuditoria } from '../types'
import ReprodutorAudioEntrada from './ReprodutorAudioEntrada.vue'
const props = withDefaults(
  defineProps<{ registro: RegistroAuditoria; audios?: AudiosEntradas }>(),
  {
    audios: () => ({}),
  },
)
const emit = defineEmits<{
  'ouvir-audio': [entradaId: string]
  'falha-audio': [entradaId: string]
}>()
const entrada = computed(() =>
  props.registro.entradas.find((item) => item.finalidade === 'entrada_inicial'),
)
const versoes = computed(() => [...props.registro.versoes].sort((a, b) => a.versao - b.versao))
const ultima = computed(() => versoes.value[versoes.value.length - 1])
const logica = computed(() =>
  ultima.value ? transformarRegra(ultima.value.representacao, { manterCodigos: true }) : undefined,
)
function entradasDaVersao(id: string) {
  return [
    ...new Set(
      props.registro.etapas
        .filter((etapa) => etapa.regra_id === id && etapa.submissao_id)
        .map((etapa) => etapa.submissao_id),
    ),
  ]
}
</script>
<template>
  <div class="space-y-7">
    <div class="grid items-start gap-6 xl:grid-cols-2">
      <section class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8">
        <p class="text-sm font-semibold text-[#a74700]">ENTRADA ORIGINAL</p>
        <h2 class="mb-6 mt-5 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
          O início da regra
        </h2>
        <template v-if="entrada"
          ><p class="mb-5 break-all text-sm">
            {{ entrada.tipo }} · {{ dataAuditoria(entrada.criado_em)
            }}<span class="mt-2 block">Entrada {{ entrada.id }}</span>
          </p>
          <pre
            v-if="entrada.tipo === 'formulario'"
            class="overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-[#fff0e9] p-6 text-sm"
            >{{ JSON.stringify(entrada.conteudo, null, 2) || 'Conteúdo não disponível.' }}</pre>
          <blockquote
            v-else
            class="whitespace-pre-wrap break-words rounded-xl bg-[#fff0e9] p-6 font-serif text-2xl leading-relaxed text-[#2e1a10]"
          >
            {{ entrada.texto ?? 'Transcrição ainda não disponível.' }}
          </blockquote>
          <ReprodutorAudioEntrada
            v-if="entrada.tipo === 'voz'"
            class="mt-4"
            :audio="audios[entrada.id]"
            :formato="entrada.formato"
            @ouvir="emit('ouvir-audio', entrada.id)"
            @falhou="emit('falha-audio', entrada.id)"
          />
          <p v-if="entrada.transcrito_em" class="mt-4 text-sm">
            Transcrição registrada em {{ dataAuditoria(entrada.transcrito_em) }}
          </p>
          <p class="mt-6 text-sm leading-6 text-[#806b5d]">
            Registro preservado como recebido no início do fluxo. Alterações posteriores aparecem
            nas versões abaixo.
          </p>
        </template>
        <p v-else>Entrada inicial não disponível.</p>
      </section>
      <section class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8">
        <p class="text-sm font-semibold text-[#a74700]">
          VERSÃO MAIS RECENTE<span v-if="ultima"> · v{{ ultima.versao }}</span>
        </p>
        <h2 class="mb-6 mt-5 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
          Lógica estruturada
        </h2>
        <div v-if="logica" class="rounded-xl bg-[#fff0e9] p-6 font-mono text-sm leading-7">
          <p>SE</p>
          <p
            v-for="(linha, indice) in logica.se"
            :key="indice"
            class="whitespace-pre-wrap break-words pl-4"
          >
            {{ linha }}
          </p>
          <p class="mt-6">ENTÃO</p>
          <p
            v-for="(linha, indice) in logica.entao"
            :key="indice"
            class="whitespace-pre-wrap break-words pl-4"
          >
            {{ linha }}
          </p>
          <p v-if="!logica.entao.length" class="pl-4">Sem efeitos adicionais registrados.</p>
        </div>
        <p v-else>Nenhuma versão registrada.</p>
      </section>
    </div>
    <section class="rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm sm:p-8">
      <p class="text-sm font-semibold text-[#a74700]">ORDEM CRONOLÓGICA</p>
      <h2 class="mb-4 mt-5 font-serif text-2xl font-bold text-[#2e1a10] sm:text-3xl">
        Histórico completo de versões
      </h2>
      <p class="mb-7">Consulte a origem e os registros vinculados a cada versão.</p>
      <p v-if="!versoes.length">Nenhuma versão registrada.</p>
      <article
        v-for="versao in versoes"
        :key="versao.id"
        class="grid gap-4 border-t border-[#f1ded3] py-7 sm:grid-cols-[4rem_1fr]"
      >
        <span class="h-fit w-fit rounded-full bg-[#fff0e9] px-4 py-1 font-semibold text-[#a74700]"
          >v{{ versao.versao }}</span
        >
        <div class="min-w-0">
          <h3 class="font-serif text-2xl font-bold text-[#2e1a10]">{{ versao.origem }}</h3>
          <p class="my-3">{{ dataAuditoria(versao.criada_em) }}</p>
          <p class="break-all text-sm">Versão {{ versao.id }}</p>
          <p
            v-for="id in entradasDaVersao(versao.id)"
            :key="id"
            class="mt-3 break-all text-sm text-[#a74700]"
          >
            Entrada {{ id }}
          </p>
          <p
            v-for="rodada in registro.rodadas.filter(
              (item) => item.regra_resultante_id === versao.id,
            )"
            :key="rodada.id"
            class="mt-3 break-all text-sm text-[#a74700]"
          >
            Rodada {{ rodada.id }}
          </p>
          <p v-if="versao.regra_origem_id" class="mt-3 break-all text-sm">
            Versão de origem {{ versao.regra_origem_id }}
          </p>
          <p
            v-for="codigo in registro.codigos.filter((item) => item.regra_id === versao.id)"
            :key="codigo.id"
            class="mt-3 break-all text-sm text-[#a74700]"
          >
            Código {{ codigo.id }} · {{ codigo.linguagem }} · {{ dataAuditoria(codigo.criado_em) }}
          </p>
        </div>
      </article>
    </section>
  </div>
</template>
