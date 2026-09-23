export async function consumirEventosSse(
  corpo: ReadableStream<Uint8Array>,
  receber: (evento: string, dados: string) => void,
): Promise<void> {
  const leitor = corpo.getReader()
  const decodificador = new TextDecoder()
  let linha = ''
  let ignorarLf = false
  let evento = ''
  let dados: string[] = []

  function processarLinha() {
    if (linha === '') {
      if (dados.length > 0) receber(evento || 'message', dados.join('\n'))
      evento = ''
      dados = []
      return
    }
    if (linha.startsWith(':')) return

    const separador = linha.indexOf(':')
    const campo = separador === -1 ? linha : linha.slice(0, separador)
    let valor = separador === -1 ? '' : linha.slice(separador + 1)
    if (valor.startsWith(' ')) valor = valor.slice(1)
    if (campo === 'event') evento = valor
    if (campo === 'data') dados.push(valor)
  }

  try {
    while (true) {
      const { done, value } = await leitor.read()
      if (done) break

      for (const caractere of decodificador.decode(value, { stream: true })) {
        if (ignorarLf && caractere === '\n') {
          ignorarLf = false
          continue
        }
        ignorarLf = false
        if (caractere === '\r' || caractere === '\n') {
          processarLinha()
          linha = ''
          ignorarLf = caractere === '\r'
        } else {
          linha += caractere
        }
      }
    }
  } finally {
    await leitor.cancel().catch(() => undefined)
    leitor.releaseLock()
  }
}
