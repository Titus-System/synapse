<script setup lang="ts">
import { computed } from 'vue'
import type { RegraVersionada } from '@/types/api'
import MensagemConversa from './MensagemConversa.vue'
import { parametrosDaRegra } from '../composables/parametrosDaRegra'
import type { Rodada } from '../types'
const props = defineProps<{
  rodadas: Rodada[]
  regras?: RegraVersionada[]
  metaVenda?: number
  competencias?: string[]
}>()
const parametros = computed(() => {
  const regra = props.regras?.find((item) => item.id === props.rodadas[0]?.regra_analisada_id)
  return regra
    ? parametrosDaRegra(regra.representacao.nucleo, props.metaVenda, props.competencias)
    : []
})
</script>

<template>
  <MensagemConversa v-if="parametros.length" data-parametros>
    <p>Olá! Entendi que você quer criar uma regra com os seguintes parâmetros:</p>
    <p v-for="parametro in parametros" :key="parametro.rotulo">
      {{ parametro.rotulo }}: {{ parametro.valor }}
    </p>
  </MensagemConversa>
  <div v-for="rodada in rodadas" :key="rodada.id" class="space-y-5" :data-rodada="rodada.id">
    <MensagemConversa v-if="rodada.conflitos.length">
      <p>Precisamos ajustar estes pontos:</p>
      <ul class="mt-2 list-disc space-y-2 pl-5">
        <li v-for="(conflito, indice) in rodada.conflitos" :key="indice">{{ conflito.motivo }}</li>
      </ul>
    </MensagemConversa>
    <MensagemConversa v-if="rodada.correcao" usuario>
      <p v-if="rodada.correcao.tipo === 'voz'" class="mb-2 text-sm font-semibold">
        Correção por voz
      </p>
      <p class="whitespace-pre-wrap">
        {{
          rodada.correcao.texto ??
          (rodada.estado === 'em_transcricao'
            ? 'Áudio enviado. Aguardando transcrição...'
            : 'Áudio sem transcrição disponível.')
        }}
      </p>
    </MensagemConversa>
        <MensagemConversa v-if="rodada.estado === 'em_transcricao'" tom="andamento">
      <p role="status" class="flex items-start gap-2 font-semibold">
        <svg class="mt-1 size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10" cy="10" r="8" /><path d="M10 6v4l3 2" stroke-linecap="round" /></svg>
        <span>Seu áudio está sendo transcrito. Aguarde para enviar outra correção.</span>
      </p>
    </MensagemConversa>
    <MensagemConversa v-else-if="rodada.estado === 'em_reextracao'" tom="andamento">
      <p role="status" class="flex items-start gap-2 font-semibold">
        <svg class="mt-1 size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10" cy="10" r="8" /><path d="M10 6v4l3 2" stroke-linecap="round" /></svg>
        <span>Sua correção está sendo interpretada. Aguarde.</span>
      </p>
    </MensagemConversa>
    <MensagemConversa v-else-if="rodada.estado === 'reextracao_falhou'" tom="erro">
      <p role="alert" class="flex items-start gap-2 font-semibold">
        <svg class="mt-1 size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10" cy="10" r="8" /><path d="M10 6v5m0 3.5h.01" stroke-linecap="round" /></svg>
        <span>
          {{
            rodada.correcao?.tipo === 'voz' && !rodada.correcao.texto
              ? 'Não foi possível transcrever seu áudio. Tente corrigir novamente por voz ou por texto.'
              : 'Não foi possível aplicar esta correção. Tente corrigir novamente por voz ou por texto.'
          }}
        </span>
      </p>
    </MensagemConversa>
    <MensagemConversa v-else-if="rodada.estado === 'corrigida'" tom="sucesso">
      <p class="flex items-start gap-2 font-semibold">
        <svg class="mt-1 size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10" cy="10" r="8" /><path d="m6.5 10.5 2.5 2.5 4.5-5" stroke-linecap="round" stroke-linejoin="round" /></svg>
        <span>A regra foi atualizada.</span>
      </p>
    </MensagemConversa>
    <MensagemConversa v-else-if="rodada.estado === 'abandonada'" tom="neutro">
      <p class="flex items-start gap-2 font-semibold">
        <svg class="mt-1 size-5 shrink-0" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10" cy="10" r="8" /><path d="M8 7.5v5M12 7.5v5" stroke-linecap="round" /></svg>
        <span>Esta correção foi encerrada.</span>
      </p>
    </MensagemConversa>
  </div>
</template>
