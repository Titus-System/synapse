export function dataAuditoria(valor?: string): string {
  if (!valor) return 'Não registrada'
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'medium',
    timeZone: 'America/Sao_Paulo',
  }).format(new Date(valor))
}
export function codigosAuditoria(codigos?: string[]): string {
  return codigos?.length ? codigos.join(', ') : codigos ? 'Todos' : 'Não informado'
}
