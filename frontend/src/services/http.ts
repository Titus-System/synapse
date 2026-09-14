import { config } from '@/config/env'
import type { ApiError, CodigoErro, ElementoErro } from '@/types/api'

const mensagensPorCodigo: Record<CodigoErro, string> = {
  requisicao_invalida: 'Não foi possível enviar os dados. Revise as informações e tente novamente.',
  nao_autenticado: 'Sua sessão não está disponível. Tente novamente.',
  sem_permissao: 'Você não tem permissão para realizar esta ação.',
  job_nao_encontrado: 'Não foi possível encontrar o processamento solicitado.',
  estado_invalido: 'Esta ação não está disponível no estado atual do processamento.',
  simulacao_inviavel: 'A simulação foi concluída, mas a regra não cabe no orçamento informado.',
  nucleo_incompleto: 'Preencha os campos obrigatórios da regra antes de continuar.',
  regra_incoerente: 'Existem informações conflitantes na regra. Revise os campos indicados.',
}

const nomesDeCampo: Record<string, string> = {
  'nucleo.vigencia': 'Vigência',
  'nucleo.vigencia.inicio': 'Início da vigência',
  'nucleo.vigencia.fim': 'Fim da vigência',
  'nucleo.loja': 'Loja',
  'nucleo.marca': 'Marca',
  'nucleo.cargo': 'Cargo',
  'nucleo.percentual': 'Percentual de comissionamento',
  competencias: 'Competências',
  orcamento: 'Orçamento',
}

export interface FieldError {
  field: string
  message: string
}

export class HttpError extends Error {
  readonly status: number
  readonly code?: CodigoErro
  readonly fieldErrors: FieldError[]

  constructor(status: number, message: string, options?: { code?: CodigoErro; fieldErrors?: FieldError[] }) {
    super(message)
    this.name = 'HttpError'
    this.status = status
    this.code = options?.code
    this.fieldErrors = options?.fieldErrors ?? []
  }
}

function nomearCampo(elemento: ElementoErro): FieldError {
  const nome = nomesDeCampo[elemento.ref] ?? elemento.ref.split('.').at(-1)?.replaceAll('_', ' ') ?? 'Campo'
  return { field: nome, message: elemento.motivo }
}

function mensagemValidacao(fieldErrors: FieldError[]): string {
  if (fieldErrors.length === 0) {
    return 'Revise os dados informados e tente novamente.'
  }

  return fieldErrors.map(({ field, message }) => `${field}: ${message}`).join(' ')
}

function pareceApiError(value: unknown): value is ApiError {
  if (typeof value !== 'object' || value === null) return false

  const candidate = value as Partial<ApiError>
  return typeof candidate.codigo === 'string' && typeof candidate.mensagem === 'string'
}

async function lerErro(response: Response): Promise<ApiError | undefined> {
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) return undefined

  try {
    const body: unknown = await response.json()
    return pareceApiError(body) ? body : undefined
  } catch {
    return undefined
  }
}

async function criarErro(response: Response): Promise<HttpError> {
  if (response.status >= 500) {
    return new HttpError(
      response.status,
      'O serviço está temporariamente indisponível. Tente novamente em alguns instantes.',
    )
  }

  const apiError = await lerErro(response)
  const fieldErrors = apiError?.elementos?.map(nomearCampo) ?? []

  if (response.status === 400 || response.status === 422) {
    return new HttpError(response.status, mensagemValidacao(fieldErrors), {
      code: apiError?.codigo,
      fieldErrors,
    })
  }

  if (apiError) {
    return new HttpError(response.status, mensagensPorCodigo[apiError.codigo], {
      code: apiError.codigo,
      fieldErrors,
    })
  }

  return new HttpError(response.status, 'Não foi possível concluir a solicitação. Tente novamente.')
}

function construirUrl(path: string): string {
  const base = config.apiBaseUrl.replace(/\/$/, '')
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${base}${normalizedPath}`
}

async function request<TResponse>(
  method: 'GET' | 'POST',
  path: string,
  options?: { body?: unknown; signal?: AbortSignal },
): Promise<TResponse> {
  const headers = new Headers({ Accept: 'application/json' })
  const hasBody = options?.body !== undefined

  if (hasBody) headers.set('Content-Type', 'application/json')

  let response: Response
  try {
    response = await fetch(construirUrl(path), {
      method,
      headers,
      body: hasBody ? JSON.stringify(options.body) : undefined,
      signal: options?.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new HttpError(0, 'Não foi possível se conectar ao serviço. Verifique sua conexão e tente novamente.')
  }

  if (!response.ok) throw await criarErro(response)

  if (response.status === 204) return undefined as TResponse
  return (await response.json()) as TResponse
}

export const http = {
  get<TResponse>(path: string, signal?: AbortSignal) {
    return request<TResponse>('GET', path, { signal })
  },
  post<TResponse, TBody = undefined>(path: string, body?: TBody, signal?: AbortSignal) {
    return request<TResponse>('POST', path, { body, signal })
  },
  url(path: string) {
    return construirUrl(path)
  },
}
