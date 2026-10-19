<script setup lang="ts">
import MensagemConversa from './MensagemConversa.vue'
import type { Rodada } from '../types'
defineProps<{ rodadas: Rodada[] }>()
</script>

<template>
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
    <MensagemConversa v-if="rodada.estado === 'em_transcricao'">
      <p role="status">Seu áudio está sendo transcrito. Aguarde para enviar outra correção.</p>
    </MensagemConversa>
    <MensagemConversa v-else-if="rodada.estado === 'em_reextracao'">
      <p role="status">Sua correção está sendo interpretada. Aguarde.</p>
    </MensagemConversa>
    <MensagemConversa v-else-if="rodada.estado === 'reextracao_falhou'">
      <p role="alert">
        {{
          rodada.correcao?.tipo === 'voz' && !rodada.correcao.texto
            ? 'Não foi possível transcrever seu áudio. Tente corrigir novamente por voz ou por texto.'
            : 'Não foi possível aplicar esta correção. Tente corrigir novamente por voz ou por texto.'
        }}
      </p>
    </MensagemConversa>
    <MensagemConversa v-else-if="rodada.estado === 'corrigida'"
      >A regra foi atualizada.</MensagemConversa
    >
    <MensagemConversa v-else-if="rodada.estado === 'abandonada'"
      >Esta correção foi encerrada.</MensagemConversa
    >
  </div>
</template>
