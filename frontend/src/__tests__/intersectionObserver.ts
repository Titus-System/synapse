// O jsdom não implementa o IntersectionObserver usado pela barra lateral para carregar mais
// regras. Este substituto nunca avisa interseção; o teste da barra lateral troca por um controlável.
if (!('IntersectionObserver' in globalThis)) {
  class ObservadorSemInterseccao {
    readonly root = null
    readonly rootMargin = '0px'
    readonly thresholds = [0]
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return []
    }
  }
  globalThis.IntersectionObserver =
    ObservadorSemInterseccao as unknown as typeof IntersectionObserver
}
