import type { App } from 'vue'

type RegistroLog = {
  timestamp: string
  level: 'ERROR'
  message: string
  'service.name': 'synapse-frontend'
  exception?: string
}

function nomeErro(erro: unknown): string | undefined {
  return erro instanceof Error ? erro.name : undefined
}

function registrarErro(mensagem: string, erro?: unknown) {
  const excecao = nomeErro(erro)
  const registro: RegistroLog = {
    timestamp: new Date().toISOString(),
    level: 'ERROR',
    message: mensagem,
    'service.name': 'synapse-frontend',
    ...(excecao === undefined ? {} : { exception: excecao }),
  }

  console.error(JSON.stringify(registro))
}

/* Registra erros do navegador sem enviar dados a outro serviço. */
export function instalarRegistroDeErrosDoNavegador(aplicacao: App) {
  aplicacao.config.errorHandler = (erro) => registrarErro('Erro não tratado pelo Vue', erro)

  window.addEventListener('error', (evento) => registrarErro('Erro não tratado pelo navegador', evento.error))
  window.addEventListener('unhandledrejection', (evento) =>
    registrarErro('Promessa rejeitada sem tratamento', evento.reason),
  )
}
