import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import EntradaTexto from './EntradaTexto.vue'

// O jsdom não calcula layout: as medidas que o navegador daria entram por aqui.
function medidas(conteudo: () => number, borda = 2) {
  const alturasLidas: string[] = []
  vi.spyOn(Element.prototype, 'scrollHeight', 'get').mockImplementation(function (this: Element) {
    alturasLidas.push((this as HTMLElement).style.height)
    return conteudo()
  })
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(
    () => conteudo() + borda,
  )
  vi.spyOn(Element.prototype, 'clientHeight', 'get').mockImplementation(() => conteudo())
  return alturasLidas
}

function montar(texto = '') {
  const wrapper = mount(EntradaTexto, {
    props: {
      modelValue: texto,
      enviando: false,
      'onUpdate:modelValue': (valor: string | undefined) =>
        wrapper.setProps({ modelValue: valor ?? '' }),
    },
    attachTo: document.body,
  })
  return wrapper
}

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

describe('entrada de texto da regra', () => {
  it('cresce com o texto até um teto proporcional à altura da janela', () => {
    const classes = montar().get('textarea').classes()

    expect(classes.some((c) => c.startsWith('max-h-[') && c.includes('dvh'))).toBe(true)
    expect(classes).toContain('resize-none')
  })

  it('fixa a altura do conteúdo mais as bordas ao montar e a cada alteração', async () => {
    let conteudo = 80
    medidas(() => conteudo)
    const wrapper = montar()
    const campo = wrapper.get('textarea')
    expect(campo.element.style.height).toBe('82px')

    conteudo = 240
    await campo.setValue('uma regra longa o bastante para ocupar várias linhas')

    expect(campo.element.style.height).toBe('242px')
  })

  it('mede de novo a partir da altura automática, para que o campo também encolha', async () => {
    let conteudo = 240
    const lidas = medidas(() => conteudo)
    const wrapper = montar('texto longo')
    const campo = wrapper.get('textarea')
    lidas.length = 0

    conteudo = 80
    await campo.setValue('curto')

    expect(lidas).toEqual(['auto'])
    expect(campo.element.style.height).toBe('82px')
  })

  it('não fixa altura quando o elemento não tem layout', () => {
    const wrapper = montar()

    expect(wrapper.get('textarea').element.style.height).toBe('auto')
  })

  it('remede quando a janela muda de tamanho e deixa de ouvir ao desmontar', async () => {
    let conteudo = 80
    medidas(() => conteudo)
    const remover = vi.spyOn(window, 'removeEventListener')
    const wrapper = montar('texto')
    const campo = wrapper.get('textarea')

    conteudo = 160
    window.dispatchEvent(new Event('resize'))

    expect(campo.element.style.height).toBe('162px')
    wrapper.unmount()
    expect(remover).toHaveBeenCalledWith('resize', expect.any(Function))
  })
})
