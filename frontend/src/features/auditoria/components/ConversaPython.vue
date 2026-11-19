<script setup lang="ts">
import { useConversaAuditoria } from '../composables/useConversaAuditoria'
import type { AudiosEntradas, RegistroAuditoria } from '../types'
import CodigoAuditoria from './CodigoAuditoria.vue'
import ConversaAuditoria from './ConversaAuditoria.vue'
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
const { codigos } = useConversaAuditoria(() => props.registro)
</script>
<template>
  <div class="grid items-stretch gap-6 xl:h-[70vh] xl:grid-cols-2" data-conversa-python>
    <div class="h-[70vh] min-h-0 xl:h-full">
      <ConversaAuditoria
        :registro="registro"
        :audios="audios"
        @ouvir-audio="emit('ouvir-audio', $event)"
        @falha-audio="emit('falha-audio', $event)"
      />
    </div>
    <div class="h-[70vh] min-h-0 xl:h-full">
      <CodigoAuditoria :codigos="codigos" />
    </div>
  </div>
</template>
