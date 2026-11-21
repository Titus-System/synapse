import { expect, it } from 'vitest'
import {
  consultaDoFiltro,
  filtroDaRota,
  mesCorrente,
  paginaDaRota,
  queryDoFiltro,
  TODOS_OS_MESES,
} from './filtrosOperacoes'
it('usa o mês corrente de Brasília, e não o de UTC, na virada do mês', () => {
  expect(mesCorrente(new Date('2026-12-01T02:30:00Z'))).toBe('2026-11')
  expect(mesCorrente(new Date('2026-12-01T03:30:00Z'))).toBe('2026-12')
})
it('sem mês no endereço, filtra pelo mês corrente e por nada mais', () => {
  expect(filtroDaRota({}, new Date('2026-11-17T12:00:00Z'))).toEqual({
    usuario: '',
    mes: '2026-11',
    loja: '',
    marca: '',
    cargo: '',
    regra: '',
  })
})
it('lê os filtros do endereço e guarda o mês, inclusive todos os meses', () => {
  const filtro = filtroDaRota({ usuario: 'rh.outro', mes: TODOS_OS_MESES, regra: ' Comissão ' })
  expect(filtro).toMatchObject({ usuario: 'rh.outro', mes: 'todos', regra: 'Comissão' })
  expect(queryDoFiltro(filtro, 2)).toEqual({
    usuario: 'rh.outro',
    mes: 'todos',
    regra: 'Comissão',
    pagina: '2',
  })
  expect(consultaDoFiltro(filtro)).toEqual({ usuario: 'rh.outro', regra: 'Comissão' })
})
it('envia à API só os filtros preenchidos', () => {
  const filtro = filtroDaRota({ mes: '2026-10', loja: '13', marca: '', cargo: '100' })
  expect(consultaDoFiltro(filtro)).toEqual({ mes: '2026-10', loja: '13', cargo: '100' })
  expect(queryDoFiltro(filtro)).toEqual({ mes: '2026-10', loja: '13', cargo: '100' })
})
it.each([
  [{}, 0],
  [{ pagina: '3' }, 3],
  [{ pagina: '-1' }, 0],
  [{ pagina: 'x' }, 0],
  [{ pagina: '1.5' }, 0],
])('lê a página %o como %i', (query, pagina) => {
  expect(paginaDaRota(query)).toBe(pagina)
})
