<script setup lang="ts">
import { dataAuditoria, estadoDaRodada } from '../composables/apresentacaoAuditoria'
import { useConversaAuditoria } from '../composables/useConversaAuditoria'
import type { AudiosEntradas, RegistroAuditoria } from '../types'
import ChamadaModelo from './ChamadaModelo.vue'
import ModeloTranscricao from './ModeloTranscricao.vue'
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
const { itens } = useConversaAuditoria(() => props.registro)
</script>
<template>
  <section
    class="flex h-full min-h-0 flex-col rounded-2xl border border-[#dec0b1] bg-white p-5 shadow-sm"
    aria-label="Conversa registrada"
  >
    <h2 class="font-serif text-2xl font-bold text-[#2e1a10]">Conversa completa</h2>
    <p v-if="!itens.length" class="mt-4">Nenhum registro na conversa.</p>
    <ol v-else class="mt-4 min-h-0 flex-1 space-y-4 overflow-y-auto pr-2" tabindex="0">
      <li v-for="(item, indice) in itens" :key="`${item.tipo}-${indice}`" :data-item="item.tipo">
        <div v-if="item.tipo === 'entrada'" class="rounded-xl bg-[#e7dfda] p-4 text-sm">
          <p class="flex flex-wrap justify-between gap-2 text-xs font-semibold">
            <span>{{ registro.job.usuario.login }}</span>
            <span>{{ dataAuditoria(item.instante) }}</span>
          </p>
          <p class="mt-2 text-xs text-[#806b5d]">
            {{ item.entrada.tipo }} ·
            {{ item.entrada.finalidade === 'correcao' ? 'Correção' : 'Entrada inicial' }}
            <template v-if="item.rodada"> · rodada {{ item.rodada }}</template>
          </p>
          <pre
            v-if="item.entrada.tipo === 'formulario'"
            class="mt-2 whitespace-pre-wrap break-words"
            >{{ JSON.stringify(item.entrada.conteudo, null, 2) ?? 'Conteúdo não disponível.' }}</pre>
          <p v-else class="mt-2 whitespace-pre-wrap break-words">
            {{ item.entrada.texto ?? 'Transcrição ainda não disponível.' }}
          </p>
          <ReprodutorAudioEntrada
            v-if="item.entrada.tipo === 'voz'"
            class="mt-3"
            :audio="audios[item.entrada.id]"
            :formato="item.entrada.formato"
            @ouvir="emit('ouvir-audio', item.entrada.id)"
            @falhou="emit('falha-audio', item.entrada.id)"
          />
          <ModeloTranscricao class="mt-2 text-xs" :entrada="item.entrada" />
        </div>
        <div v-else-if="item.tipo === 'correcao_rodada'" class="rounded-xl bg-[#e7dfda] p-4 text-sm">
          <p class="flex flex-wrap justify-between gap-2 text-xs font-semibold">
            <span>{{ registro.job.usuario.login }}</span>
            <span>{{ dataAuditoria(item.instante) }}</span>
          </p>
          <p class="mt-2 text-xs text-[#806b5d]">
            {{ item.rodada.correcao?.tipo ?? 'texto' }} · Correção · rodada {{ item.numero }} · registrada na rodada
          </p>
          <p class="mt-2 whitespace-pre-wrap break-words">
            {{ item.rodada.correcao?.texto ?? 'Transcrição ainda não disponível.' }}
          </p>
        </div>
        <div v-else-if="item.tipo === 'conflitos'" class="rounded-xl bg-[#fff1ec] p-4 text-sm">
          <p class="flex flex-wrap justify-between gap-2 text-xs font-semibold">
            <span>Sistema · conflitos da rodada {{ item.numero }}</span>
            <span>{{ dataAuditoria(item.instante) }}</span>
          </p>
          <ul class="mt-2 list-disc space-y-1 pl-5">
            <li v-for="(conflito, i) in item.rodada.conflitos" :key="i">{{ conflito.motivo }}</li>
          </ul>
          <p class="mt-2 text-xs font-semibold" :title="item.rodada.estado">
            Situação: {{ estadoDaRodada(item.rodada.estado) }}
          </p>
        </div>
        <ChamadaModelo v-else-if="item.tipo === 'chamada'" :chamada="item.chamada" />
        <p
          v-else-if="item.tipo === 'versao'"
          class="rounded-xl border border-[#dec0b1] px-4 py-2 text-sm break-all"
        >
          Versão {{ item.versao.versao }} registrada ·
          <span :title="item.versao.id" class="font-mono">{{ item.versao.id.slice(0, 8) }}</span> ·
          {{ dataAuditoria(item.instante) }}
        </p>
        <p v-else class="rounded-xl border border-[#dec0b1] px-4 py-2 text-sm break-all">
          Código registrado
          <template v-if="item.versao">(versão {{ item.versao }})</template> ·
          <span :title="item.codigo.id" class="font-mono">{{ item.codigo.id.slice(0, 8) }}</span> ·
          {{ dataAuditoria(item.instante) }}
        </p>
      </li>
    </ol>
  </section>
</template>