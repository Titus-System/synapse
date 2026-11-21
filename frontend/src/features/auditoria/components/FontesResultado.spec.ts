import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FontesResultado from './FontesResultado.vue'
import type { FontesResultadoAuditoria } from '../types'

const sha = (letra: string) => letra.repeat(64)
const fontesExemplo: FontesResultadoAuditoria = {
  manifesto: { versao: 3, congelamento: '2026-11-01' },
  competencias: ['2025-10', '2025-11'],
  arquivos: [
    { nome: 'vendas.csv', sha256: sha('a') },
    { nome: 'comissoes.csv', sha256: sha('b') },
  ],
  baselines: [
    { competencia: '2025-10', arquivo: 'baselines/2025-10.json', sha256: sha('c') },
    { competencia: '2025-11', arquivo: 'baselines/2025-11.json', sha256: sha('d') },
  ],
}

describe('FontesResultado', () => {
  it('mostra a versão e o congelamento das bases e as competências processadas', () => {
    const w = mount(FontesResultado, { props: { fontes: fontesExemplo } })
    expect(w.get('[data-versao-bases]').text()).toBe('v3')
    expect(w.text()).toContain('01/11/2026')
    expect(w.text()).toContain('2025-10, 2025-11')
    expect(w.find('[data-sem-fontes]').exists()).toBe(false)
  })

  it('mostra cada arquivo com o sha256 inteiro, como veio', () => {
    const arquivos = mount(FontesResultado, { props: { fontes: fontesExemplo } })
      .get('[data-arquivos]')
      .text()
    expect(arquivos).toContain('Arquivos de base (2)')
    expect(arquivos).toContain('vendas.csv')
    expect(arquivos).toContain(sha('a'))
    expect(arquivos).toContain('comissoes.csv')
    expect(arquivos).toContain(sha('b'))
  })

  it('mostra o baseline de cada competência com arquivo e sha256', () => {
    const w = mount(FontesResultado, { props: { fontes: fontesExemplo } })
    const outubro = w.get('[data-baseline="2025-10"]').text()
    expect(outubro).toContain('baselines/2025-10.json')
    expect(outubro).toContain(sha('c'))
    expect(w.get('[data-baseline="2025-11"]').text()).toContain(sha('d'))
  })

  it('mostra o estado sem fontes', () => {
    const w = mount(FontesResultado, { props: {} })
    expect(w.get('[data-sem-fontes]').text()).toContain('Sem fontes registradas')
    expect(w.find('[data-arquivos]').exists()).toBe(false)
  })
})
