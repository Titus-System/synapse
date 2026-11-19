import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReprodutorAudioEntrada from './ReprodutorAudioEntrada.vue'

describe('ReprodutorAudioEntrada', () => {
  it('oferece ouvir o áudio antes de baixá-lo', async () => {
    const wrapper = mount(ReprodutorAudioEntrada, { props: { formato: 'ogg' } })

    expect(wrapper.find('audio').exists()).toBe(false)
    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('ouvir')).toHaveLength(1)
  })

  it('informa o carregamento', () => {
    const wrapper = mount(ReprodutorAudioEntrada, {
      props: { formato: 'ogg', audio: { estado: 'carregando' } },
    })

    expect(wrapper.get('[role="status"]').text()).toBe('Carregando áudio…')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('toca o arquivo baixado pela URL local', async () => {
    const wrapper = mount(ReprodutorAudioEntrada, {
      props: { formato: 'ogg', audio: { estado: 'pronto', url: 'blob:audio-1' } },
    })

    const audio = wrapper.get('audio')
    expect(audio.attributes('src')).toBe('blob:audio-1')
    expect(audio.attributes()).toHaveProperty('controls')
    await audio.trigger('error')
    expect(wrapper.emitted('falhou')).toHaveLength(1)
  })

  it('mostra o erro sem detalhe interno e permite tentar de novo', async () => {
    const wrapper = mount(ReprodutorAudioEntrada, {
      props: { formato: 'ogg', audio: { estado: 'erro' } },
    })

    expect(wrapper.get('[role="alert"]').text()).toContain('Não foi possível carregar o áudio.')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('ouvir')).toHaveLength(1)
  })

  it('informa o áudio indisponível sem oferecer download', () => {
    const naoEncontrado = mount(ReprodutorAudioEntrada, {
      props: { formato: 'ogg', audio: { estado: 'indisponivel' } },
    })
    const semFormato = mount(ReprodutorAudioEntrada, { props: {} })

    for (const wrapper of [naoEncontrado, semFormato]) {
      expect(wrapper.text()).toContain('Áudio indisponível para esta entrada.')
      expect(wrapper.find('button').exists()).toBe(false)
      expect(wrapper.find('audio').exists()).toBe(false)
    }
  })
})
