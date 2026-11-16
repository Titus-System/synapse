import type { RegistroAuditoria } from '../types'
export function exportarDossie(registro: RegistroAuditoria): void {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(registro, null, 2)], { type: 'application/json' }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = 'dossie-' + registro.job.id + '.json'
  document.body.append(link)
  try {
    link.click()
  } finally {
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
