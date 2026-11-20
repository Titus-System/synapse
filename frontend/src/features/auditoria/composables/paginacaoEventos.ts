/** As páginas que a paginação mostra: três em torno da atual, a primeira e a última. */
export function paginasVisiveis(pagina: number, total: number, tamanho: number): number[] {
  const paginas = Math.max(1, Math.ceil(total / tamanho))
  const inicio = Math.max(0, Math.min(pagina - 1, paginas - 3))
  const numeros = new Set([0, inicio, inicio + 1, inicio + 2, paginas - 1])
  return [...numeros].filter((numero) => numero < paginas).sort((a, b) => a - b)
}
