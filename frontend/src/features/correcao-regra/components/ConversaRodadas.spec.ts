import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import ConversaRodadas from './ConversaRodadas.vue'
import { rodadaVoz, pendente } from '../services/correcao.fixtures'
it('substitui espera por transcrição escapada, preserva indicação de voz e não duplica na reconciliação', async () => {
  const wrapper = mount(ConversaRodadas, { props: { rodadas: [rodadaVoz] } })
  expect(wrapper.text()).toContain('Seu áudio está sendo transcrito')
  expect(wrapper.text()).toContain('Correção por voz')
  const rodada = {
    ...rodadaVoz,
    estado: 'em_reextracao' as const,
    correcao: { ...rodadaVoz.correcao!, texto: '<script>privado</script>' },
  }
  await wrapper.setProps({ rodadas: [rodada] })
  await wrapper.setProps({ rodadas: [structuredClone(rodada)] })
  expect(wrapper.findAll('[data-rodada]')).toHaveLength(1)
  expect(wrapper.text()).toContain('<script>privado</script>')
  expect(wrapper.find('script').exists()).toBe(false)
  expect(wrapper.text()).toContain('Sua correção está sendo interpretada')
  expect(wrapper.text()).not.toContain('Aguardando transcrição')
  expect(wrapper.text()).not.toContain('nucleo.percentual')
})
it('mostra falha de transcrição e convida à nova tentativa por voz ou texto', () => {
  const wrapper = mount(ConversaRodadas, {
    props: {
      rodadas: [
        { ...rodadaVoz, estado: 'reextracao_falhou' },
        { ...pendente, id: 'nova' },
      ],
    },
  })
  expect(wrapper.get('[role="alert"]').text()).toContain('Não foi possível transcrever seu áudio')
  expect(wrapper.get('[role="alert"]').text()).toContain('voz ou por texto')
  expect(wrapper.text()).not.toContain('Aguardando transcrição')
})
it('distingue falha de reextração de voz já transcrita e mantém histórico de texto compatível', () => {
  const wrapper = mount(ConversaRodadas, {
    props: {
      rodadas: [
        {
          ...rodadaVoz,
          estado: 'reextracao_falhou',
          correcao: { ...rodadaVoz.correcao!, texto: 'correcao' },
        },
        {
          ...pendente,
          id: 'texto',
          estado: 'corrigida',
          correcao: { texto: 'texto anterior', enviada_em: pendente.criada_em },
        },
      ],
    },
  })
  expect(wrapper.text()).toContain('Não foi possível aplicar esta correção')
  expect(wrapper.text()).toContain('texto anterior')
  expect(wrapper.text()).toContain('A regra foi atualizada')
})
