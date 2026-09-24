import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import TheProcessHeader from './TheProcessHeader.vue'

const opcoesDeMontagem = {
  global: {
    plugins: [createPinia()],
  },
}

describe('TheProcessHeader', () => {
  it('marca a entrada de regra como etapa atual', () => {
    const conteiner = mount(TheProcessHeader, { ...opcoesDeMontagem, props: { etapaDaRota: 'voz-texto' } })

    expect(conteiner.get('li[aria-current="step"]').text()).toContain('Voz/Texto')
  })

  it('associa os estados intermediários à simulação enquanto a conversa não possui tela própria', () => {
    const conteiner = mount(TheProcessHeader, {
      ...opcoesDeMontagem,
      props: { etapaDaRota: 'simulacao', statusDoJob: 'aguardando_confirmacao_parametros' },
    })

    expect(conteiner.get('li[aria-current="step"]').text()).toContain('Simulação')
    expect(conteiner.text()).not.toContain('Conversa')
  })

  it('indica o salvamento em toda a tela de finalização, mesmo durante uma transição de status', () => {
    const conteiner = mount(TheProcessHeader, {
      ...opcoesDeMontagem,
      props: { etapaDaRota: 'salvar', statusDoJob: 'simulacao_inviavel' },
    })

    expect(conteiner.get('li[aria-current="step"]').text()).toContain('Salvar')
  })

  it('não exibe o progresso de uma nova regra no histórico', () => {
    const conteiner = mount(TheProcessHeader, { ...opcoesDeMontagem, props: { etapaDaRota: null } })

    expect(conteiner.find('[aria-label="Etapas do processo"]').exists()).toBe(false)
    expect(conteiner.find('[aria-label^="Etapa atual:"]').exists()).toBe(false)
  })

  it('mantém um indicador textual acessível fora do desktop', () => {
    const conteiner = mount(TheProcessHeader, { ...opcoesDeMontagem, props: { etapaDaRota: 'simulacao' } })
    const indicador = conteiner.get('[aria-label="Etapa atual: Simulação"]')

    expect(indicador.text()).toContain('Etapa: Simulação')
    expect(indicador.classes()).toContain('xl:hidden')
  })

  it('usa um ícone reconhecível para abrir o menu de perfil', () => {
    const conteiner = mount(TheProcessHeader, { ...opcoesDeMontagem, props: { etapaDaRota: 'voz-texto' } })
    const menuDePerfil = conteiner.get('summary[aria-label="Abrir menu de perfil"]')

    expect(menuDePerfil.find('svg').attributes('viewBox')).toBe('0 0 24 24')
    expect(menuDePerfil.text()).not.toContain('U')
  })
})
