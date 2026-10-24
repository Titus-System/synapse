import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import type { JobResumo } from '@/types/api'
import { usarStoreRegrasRecentes } from './regrasRecentes'

vi.mock('@/services/api', () => ({
  apiClient: {
    listarJobs: vi.fn<typeof apiClient.listarJobs>(),
  },
}))

const schema = JSON.parse(
  readFileSync(
    resolve(dirname(fileURLToPath(import.meta.url)), '../../../contracts/observability/log.schema.json'),
    'utf8',
  ),
)

function resumo(numero: number, nome?: string | null): JobResumo {
  return {
    id: `job-${numero}`,
    nome,
    status: 'liberado',
    competencias: [],
    criado_em: '2026-09-19T12:00:00Z',
  }
}

// A api devolve os jobs do mais novo para o mais antigo; a lista abaixo segue essa ordem.
let jobsNoServidor: JobResumo[] = []

function servirJobsPaginados() {
  vi.mocked(apiClient.listarJobs).mockImplementation(async ({ pagina = 0, tamanho = 20 } = {}) => ({
    itens: jobsNoServidor.slice(pagina * tamanho, pagina * tamanho + tamanho),
    pagina,
    tamanho,
    total: jobsNoServidor.length,
  }))
}

function criarJobs(quantidade: number, primeiro = 1): JobResumo[] {
  return Array.from({ length: quantidade }, (_, indice) => resumo(primeiro + indice))
}

function identificadores(store: ReturnType<typeof usarStoreRegrasRecentes>): string[] {
  return store.regras.map((regra) => regra.identificador)
}

function registros() {
  return [...vi.mocked(console.info).mock.calls, ...vi.mocked(console.warn).mock.calls].map(
    ([linha]) => JSON.parse(String(linha)),
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'warn').mockImplementation(() => undefined)
})

afterEach(() => vi.restoreAllMocks())

describe('usarStoreRegrasRecentes', () => {
  it('começa pelas 12 regras mais recentes e conhece o total', async () => {
    jobsNoServidor = criarJobs(30)
    servirJobsPaginados()
    const store = usarStoreRegrasRecentes()

    await store.atualizar()

    expect(apiClient.listarJobs).toHaveBeenCalledExactlyOnceWith({ pagina: 0, tamanho: 12 })
    expect(identificadores(store)).toEqual(criarJobs(12).map((job) => job.id))
    expect(store.total).toBe(30)
    expect(store.todasCarregadas).toBe(false)
  })

  it('carrega as páginas seguintes até a última e então para de consultar', async () => {
    jobsNoServidor = criarJobs(30)
    servirJobsPaginados()
    const store = usarStoreRegrasRecentes()

    await store.atualizar()
    await store.carregarMais()
    await store.carregarMais()

    expect(identificadores(store)).toEqual(jobsNoServidor.map((job) => job.id))
    expect(store.todasCarregadas).toBe(true)

    await store.carregarMais()
    expect(apiClient.listarJobs).toHaveBeenCalledTimes(3)
    expect(vi.mocked(apiClient.listarJobs).mock.calls.map(([parametros]) => parametros)).toEqual([
      { pagina: 0, tamanho: 12 },
      { pagina: 1, tamanho: 12 },
      { pagina: 2, tamanho: 12 },
    ])
  })

  it('usa o nome da regra e, sem nome, o rótulo com a data', async () => {
    jobsNoServidor = [resumo(1, 'Comissão de novembro'), resumo(2, null)]
    servirJobsPaginados()
    const store = usarStoreRegrasRecentes()

    await store.atualizar()

    expect(store.regras).toEqual([
      { identificador: 'job-1', rotulo: 'Comissão de novembro' },
      {
        identificador: 'job-2',
        rotulo: `Regra · ${new Date('2026-09-19T12:00:00Z').toLocaleDateString('pt-BR')}`,
      },
    ])
  })

  it('ao atualizar, põe no topo as regras novas e mantém as páginas já carregadas', async () => {
    jobsNoServidor = criarJobs(30)
    servirJobsPaginados()
    const store = usarStoreRegrasRecentes()
    await store.atualizar()
    await store.carregarMais()

    jobsNoServidor = [...criarJobs(2, 101), ...jobsNoServidor]
    await store.atualizar()

    expect(identificadores(store)).toEqual(jobsNoServidor.slice(0, 26).map((job) => job.id))

    await store.carregarMais()
    expect(identificadores(store)).toEqual(jobsNoServidor.map((job) => job.id))
    expect(store.todasCarregadas).toBe(true)
  })

  it('recomeça da primeira página quando surgem regras novas demais para emendar a lista', async () => {
    jobsNoServidor = criarJobs(24)
    servirJobsPaginados()
    const store = usarStoreRegrasRecentes()
    await store.atualizar()

    jobsNoServidor = [...criarJobs(15, 101), ...jobsNoServidor]
    await store.atualizar()
    await store.carregarMais()
    await store.carregarMais()
    await store.carregarMais()

    expect(identificadores(store)).toEqual(jobsNoServidor.map((job) => job.id))
  })

  it('não dispara outra página enquanto uma consulta está em andamento', async () => {
    jobsNoServidor = criarJobs(30)
    servirJobsPaginados()
    const store = usarStoreRegrasRecentes()
    await store.atualizar()

    const primeira = store.carregarMais()
    const segunda = store.carregarMais()
    await Promise.all([primeira, segunda])

    expect(apiClient.listarJobs).toHaveBeenCalledTimes(2)
    expect(store.regras).toHaveLength(24)
  })

  it('sem regras, informa o total zero e não tenta outra página', async () => {
    jobsNoServidor = []
    servirJobsPaginados()
    const store = usarStoreRegrasRecentes()

    await store.atualizar()
    await store.carregarMais()

    expect(store.total).toBe(0)
    expect(store.todasCarregadas).toBe(true)
    expect(apiClient.listarJobs).toHaveBeenCalledOnce()
  })

  it('na falha, mantém as regras carregadas e se recupera na próxima consulta', async () => {
    jobsNoServidor = criarJobs(30)
    servirJobsPaginados()
    const store = usarStoreRegrasRecentes()
    await store.atualizar()

    vi.mocked(apiClient.listarJobs).mockRejectedValueOnce(
      new HttpError(503, 'detalhe interno confidencial'),
    )
    await store.carregarMais()

    expect(store.falhou).toBe(true)
    expect(store.regras).toHaveLength(12)

    await store.atualizar()
    await store.carregarMais()

    expect(store.falhou).toBe(false)
    expect(store.regras).toHaveLength(24)
  })

  it('registra cada consulta no envelope de log, sem identificadores nem nomes de regras', async () => {
    jobsNoServidor = [resumo(1, 'Comissão confidencial'), ...criarJobs(20, 2)]
    servirJobsPaginados()
    const store = usarStoreRegrasRecentes()
    await store.atualizar()
    vi.mocked(apiClient.listarJobs).mockRejectedValueOnce(new HttpError(503, 'detalhe confidencial'))
    await store.carregarMais()

    const logs = registros()
    expect(logs).toHaveLength(2)
    for (const registro of logs) {
      for (const campo of schema.required) expect(registro).toHaveProperty(campo)
      expect(schema.properties.level.enum).toContain(registro.level)
      expect(registro['service.name']).toBe('synapse-frontend')
      expect(registro.message).toBe('Consulta de regras da barra lateral concluída')
      expect(new Date(registro.timestamp).toISOString()).toBe(registro.timestamp)
      expect(registro).not.toHaveProperty('job_id')
      expect(registro.extra.operacao).toBe('listar_regras_recentes')
      expect(registro.extra.duracao_ms).toBeGreaterThanOrEqual(0)
    }
    expect(logs[0]).toMatchObject({ level: 'INFO', extra: { resultado: 'sucesso', pagina: 0 } })
    expect(logs[1]).toMatchObject({
      level: 'WARN',
      extra: { resultado: 'falha', pagina: 1, status_http: 503 },
    })
    expect(JSON.stringify(logs)).not.toMatch(/job-\d|confidencial/)
  })
})
