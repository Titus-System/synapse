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
const regraAnalisada = {
  id: pendente.regra_analisada_id,
  versao: 1,
  origem: 'extracao' as const,
  criada_em: '2025-11-24T14:00:00Z',
  representacao: {
    nucleo: {
      vigencia: { inicio: '2025-08', fim: '2025-12' },
      marca: ['10', '20'],
      percentual: 0.05,
    },
    especificacoes: [],
  },
}
it('abre a conversa com os parâmetros entendidos e os campos vazios como todos', () => {
  const wrapper = mount(ConversaRodadas, {
    props: { rodadas: [pendente], regras: [regraAnalisada], metaVenda: 200000 },
  })
  const mensagem = wrapper.get('[data-parametros]').text()
  expect(mensagem).toContain('Olá! Entendi que você quer criar uma regra com os seguintes parâmetros:')
  expect(mensagem).toContain('Validade: 08/2025 até 12/2025')
  expect(mensagem).toContain('Produto: 10, 20')
  expect(mensagem).toContain('Canal: Todos')
  expect(mensagem).toContain('Equipes: Todos')
  expect(mensagem).toContain('Marcas: 10, 20')
  expect(mensagem).toContain('Comissionamento: 5%')
  expect(mensagem).toContain('Meta de vendas: R$ 200.000,00')
  expect(mensagem).toContain('Podemos prosseguir para a simulação?')
  expect(wrapper.text().indexOf('Olá!')).toBeLessThan(wrapper.text().indexOf('Precisamos ajustar'))
})
it('mostra o que faltou quando a regra não traz vigência, percentual nem meta', () => {
  const wrapper = mount(ConversaRodadas, {
    props: {
      rodadas: [pendente],
      regras: [{ ...regraAnalisada, representacao: { nucleo: {}, especificacoes: [] } }],
    },
  })
  const mensagem = wrapper.get('[data-parametros]').text()
  expect(mensagem).toContain('Validade: Todo o período')
  expect(mensagem).toContain('Comissionamento: Não informado')
  expect(mensagem).toContain('Meta de vendas: Não informada')
})
it('não abre a conversa sem a regra analisada e não a repete nas rodadas seguintes', () => {
  const sem = mount(ConversaRodadas, { props: { rodadas: [pendente], regras: [] } })
  expect(sem.find('[data-parametros]').exists()).toBe(false)
  const duas = mount(ConversaRodadas, {
    props: { rodadas: [{ ...pendente, estado: 'corrigida' }, { ...pendente, id: 'nova' }], regras: [regraAnalisada] },
  })
  expect(duas.findAll('[data-parametros]')).toHaveLength(1)
})
