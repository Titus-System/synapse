import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import ConversaRodadas from './ConversaRodadas.vue'
import { rodadaVoz, pendente, falhou, corrigida, abandonada } from '../services/correcao.fixtures'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Conflito } from '@/types/api'

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
it('abre a conversa com nomes e distingue os campos não informados', () => {
  const wrapper = mount(ConversaRodadas, {
    props: { rodadas: [pendente], regras: [regraAnalisada], metaVenda: 200000 },
  })
  const mensagem = wrapper.get('[data-parametros]').text()
  expect(mensagem).toContain(
    'Olá! Entendi que você quer criar uma regra com os seguintes parâmetros:',
  )
  expect(mensagem).toContain('Validade: 08/2025 até 12/2025')
  expect(mensagem).toContain('Produto: PRETO, BRANCO')
  expect(mensagem).toContain('Canal: Não informado')
  expect(mensagem).toContain('Equipes: Não informado')
  expect(mensagem).toContain('Marcas: PRETO, BRANCO')
  expect(mensagem).toContain('Comissionamento: 5%')
  expect(mensagem).toContain('Meta de vendas: R$ 200.000,00')
  expect(mensagem).not.toContain('Podemos prosseguir para a simulação?')
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
    props: {
      rodadas: [
        { ...pendente, estado: 'corrigida' },
        { ...pendente, id: 'nova' },
      ],
      regras: [regraAnalisada],
    },
  })
  expect(duas.findAll('[data-parametros]')).toHaveLength(1)
})

it('usa as competências conhecidas do job ao apresentar a vigência padrão', () => {
  const wrapper = mount(ConversaRodadas, {
    props: {
      rodadas: [pendente],
      regras: [
        {
          ...regraAnalisada,
          representacao: {
            nucleo: {
              marca: [],
              cargo: [],
              loja: [],
              taxas_por_cargo: [
                { cargo: '100', percentual: 0.03 },
                { cargo: '200', percentual: 0.025 },
              ],
            },
            especificacoes: [],
          },
        },
      ],
      competencias: ['2025-08', '2025-10', '2025-12'],
    },
  })
  const resumo = wrapper.get('[data-parametros]').text()
  expect(resumo).toContain('Validade: 08/2025, 10/2025, 12/2025')
  expect(resumo).toContain('Comissionamento: 3%, 2,5%')
  expect(resumo).not.toContain('competências não disponíveis')
})
it('mostra três rodadas em ordem, com conflito, correção e desfecho', () => {
  const aberta = { ...pendente, id: 'aberta', rodada_anterior_id: falhou.id }
  const wrapper = mount(ConversaRodadas, { props: { rodadas: [corrigida, falhou, aberta] } })
  const blocos = wrapper.findAll('[data-rodada]').map((b) => b.attributes('data-rodada'))
  expect(blocos).toEqual([corrigida.id, falhou.id, 'aberta'])
  const texto = wrapper.text()
  expect(texto.indexOf('o percentual é 5%')).toBeLessThan(texto.indexOf('A regra foi atualizada'))
  expect(texto.indexOf('A regra foi atualizada')).toBeLessThan(
    texto.indexOf('Não foi possível aplicar esta correção'),
  )
  expect(texto.split('percentual ausente')).toHaveLength(4)
})

it('mostra a rodada abandonada como encerrada, sem termos técnicos', () => {
  const wrapper = mount(ConversaRodadas, { props: { rodadas: [abandonada] } })
  const texto = wrapper.text().toLowerCase()
  for (const termo of ['job', 'veredito', 'liberado', 'versão', 'nucleo.']) {
    expect(texto).not.toContain(termo)
  }
  expect(wrapper.text()).toContain('Esta correção foi encerrada')
})
it('mostra os conflitos reais do contrato em termos do usuário, sem os identificadores internos', () => {
  const conflitos = JSON.parse(
    readFileSync(
      resolve(__dirname, '../../../../../contracts/examples/domain/conflitos-rodada.json'),
      'utf8',
    ),
  ) as Conflito[]
  const wrapper = mount(ConversaRodadas, { props: { rodadas: [{ ...pendente, conflitos }] } })
  const texto = wrapper.text()
  for (const conflito of conflitos) expect(texto).toContain(conflito.motivo)
  expect(wrapper.findAll('li')).toHaveLength(conflitos.length)
  expect(texto).not.toContain('nucleo.')
  expect(texto).not.toContain('elem.2')
})