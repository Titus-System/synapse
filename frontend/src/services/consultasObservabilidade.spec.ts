import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from './api'
import { consultarDetalhamento } from './detalhamento'
import { jobFixture, respostaPendente } from './job.fixtures'
vi.mock('@/services/keycloak', () => ({ obterTokenDeAcesso: async () => 'token-confidencial' }))
const schema = JSON.parse(
  readFileSync(
    resolve(
      dirname(fileURLToPath(import.meta.url)),
      '../../../contracts/observability/log.schema.json',
    ),
    'utf8',
  ),
)
beforeEach(() => {
  vi.spyOn(console, 'info').mockImplementation(() => undefined)
  vi.spyOn(console, 'warn').mockImplementation(() => undefined)
})
afterEach(() => vi.restoreAllMocks())
function logs() {
  const registros = [
    ...vi.mocked(console.info).mock.calls,
    ...vi.mocked(console.warn).mock.calls,
  ].map(([linha]) => JSON.parse(String(linha)))
  expect(registros.length).toBeGreaterThan(0)
  for (const registro of registros) {
    expect(Object.keys(registro).sort()).toEqual(
      ['timestamp', 'level', 'message', 'service.name', 'job_id', 'extra'].sort(),
    )
    for (const campo of schema.required) expect(registro).toHaveProperty(campo)
    expect(schema.properties.level.enum).toContain(registro.level)
    expect(schema.properties['service.name'].enum).toContain(registro['service.name'])
    expect(registro['service.name']).toBe('synapse-frontend')
    expect(registro.message).toBe('Consulta do job no navegador')
    expect(new Date(registro.timestamp).toISOString()).toBe(registro.timestamp)
    expect(registro.job_id).toEqual(expect.any(String))
    expect(registro.job_id.length).toBeGreaterThanOrEqual(schema.properties.job_id.minLength)
    expect(['consultar_job', 'consultar_detalhamento']).toContain(registro.extra.operacao)
    expect(['iniciada', 'sucesso', 'falha', 'cancelada']).toContain(registro.extra.resultado)
    expect(registro.extra.duracao_ms ?? 0).toBeGreaterThanOrEqual(0)
    expect(
      Object.keys(registro.extra).every((campo) =>
        ['operacao', 'resultado', 'duracao_ms', 'status_http'].includes(campo),
      ),
    ).toBe(true)
  }
  expect(JSON.stringify(registros)).not.toMatch(
    /token-confidencial|proposta-confidencial|pessoa-confidencial|segredo-interno|erro-confidencial/,
  )
  return registros
}
it('registra início e sucesso de consultas reais sem conteúdo e preserva correlação entre jobs', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ ...jobFixture(), motivo: 'proposta-confidencial' })),
    )
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          simulacao_id: 'sim-2',
          linhas: { '2025-11': { 'pessoa-confidencial': {} } },
        }),
      ),
    )
  await apiClient.consultarJob('job-1')
  await consultarDetalhamento('job-2', 'sim-2')
  expect(
    logs().map((registro) => [registro.job_id, registro.extra.operacao, registro.extra.resultado]),
  ).toEqual([
    ['job-1', 'consultar_job', 'iniciada'],
    ['job-1', 'consultar_job', 'sucesso'],
    ['job-2', 'consultar_detalhamento', 'iniciada'],
    ['job-2', 'consultar_detalhamento', 'sucesso'],
  ])
})
it('registra falha sanitizada e duração sem detalhes da resposta nem da exceção', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({ codigo: 'simulacao_nao_encontrada', mensagem: 'segredo-interno' }),
        { status: 404 },
      ),
    )
    .mockRejectedValueOnce(new Error('erro-confidencial'))
  await expect(consultarDetalhamento('job-1', 'sim-1')).rejects.toBeInstanceOf(Error)
  await expect(apiClient.consultarJob('job-2')).rejects.toBeInstanceOf(Error)
  const falhas = logs().filter((registro) => registro.extra.resultado === 'falha')
  expect(falhas).toHaveLength(2)
  expect(falhas.map((registro) => registro.level)).toEqual(['WARN', 'WARN'])
  expect(falhas[0].extra.status_http).toBe(404)
})
it('registra cancelamento com o job original, sem atribuí-lo à consulta seguinte', async () => {
  const pendente = respostaPendente<Response>()
  vi.spyOn(globalThis, 'fetch')
    .mockReturnValueOnce(pendente.promise)
    .mockResolvedValueOnce(new Response(JSON.stringify(jobFixture())))
  const controle = new AbortController()
  const anterior = consultarDetalhamento('job-antigo', 'sim-antiga', controle.signal)
  await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1))
  controle.abort()
  await apiClient.consultarJob('job-novo')
  pendente.resolve(new Response(JSON.stringify({ simulacao_id: 'sim-antiga' })))
  await anterior
  const registros = logs()
  expect(registros.find((registro) => registro.extra.resultado === 'cancelada')?.job_id).toBe(
    'job-antigo',
  )
  expect(registros.find((registro) => registro.extra.resultado === 'sucesso')?.job_id).toBe(
    'job-novo',
  )
})
