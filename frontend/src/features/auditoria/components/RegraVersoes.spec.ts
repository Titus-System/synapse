import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RegraVersoes from './RegraVersoes.vue'
import { registroExemplo } from '../composables/registroAuditoria.fixture'

describe('RegraVersoes', () => {
  it('avisa a falha do resumo no lugar da comparação e pede nova tentativa', async () => {
    const wrapper = mount(RegraVersoes, {
      props: { registro: registroExemplo, erroResumo: 'Não foi possível carregar os registros.' },
    })
    const alerta = wrapper.get('[role="alert"][aria-label="Comparação de versões"]')
    expect(alerta.text()).toContain('Não foi possível carregar os registros.')
    await alerta.get('button').trigger('click')
    expect(wrapper.emitted('tentar-novamente-resumo')).toHaveLength(1)
  })

  it('mostra o carregamento do resumo no lugar da comparação', () => {
    const wrapper = mount(RegraVersoes, {
      props: { registro: registroExemplo, carregandoResumo: true },
    })
    expect(wrapper.text()).toContain('Carregando a comparação de versões')
  })

  it('mostra o reprodutor na entrada original por voz e pede o áudio dela', async () => {
    const wrapper = mount(RegraVersoes, { props: { registro: registroExemplo } })

    await wrapper.get('[data-reprodutor-audio] button').trigger('click')

    expect(wrapper.emitted('ouvir-audio')).toEqual([[registroExemplo.entradas[0]!.id]])
  })
    it('mostra rótulos legíveis, sem UUIDs, e copia o id completo', async () => {
      const registro = structuredClone(registroExemplo)
      const wrapper = mount(RegraVersoes, { props: { registro } })
      const texto = wrapper.text()
      expect(texto).toContain('Versão 2')
      expect(texto).toContain('Versão de origem 1')
      expect(texto).toContain('Código 1')
      expect(texto).toContain('Rodada 1')
      expect(texto).toContain('Correção 1')
      expect(texto).not.toContain(registro.versoes[0]!.id)
      expect(texto).not.toContain(registro.codigos[0]!.id)
      expect(texto).not.toContain(registro.codigos[0]!.id.slice(0, 8) + '…')
      expect(wrapper.find(`button[title="${registro.codigos[0]!.id}"]`).exists()).toBe(true)
    })
  it.each(['formulario', 'texto'] as const)('não mostra reprodutor na entrada por %s', (tipo) => {
    const registro = structuredClone(registroExemplo)
    Object.assign(registro.entradas[0]!, { tipo, formato: undefined, conteudo: {} })

    const wrapper = mount(RegraVersoes, { props: { registro } })

    expect(wrapper.find('[data-reprodutor-audio]').exists()).toBe(false)
  })
})
