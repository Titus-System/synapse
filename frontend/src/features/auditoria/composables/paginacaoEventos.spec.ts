import { expect, it } from 'vitest'
import { paginasVisiveis } from './paginacaoEventos'
it.each([
  [0, 248, [0, 1, 2, 20]],
  [1, 248, [0, 1, 2, 20]],
  [10, 248, [0, 9, 10, 11, 20]],
  [20, 248, [0, 18, 19, 20]],
  [0, 12, [0]],
  [0, 0, [0]],
  [1, 24, [0, 1]],
])('na página %i de %i eventos mostra %o', (pagina, total, esperado) => {
  expect(paginasVisiveis(pagina, total, 12)).toEqual(esperado)
})
