import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { jobCriadoFixture, jobFixture, regraFixture } from '@/services/job.fixtures'
import type { NucleoRegra } from '@/types/api'
import { useFormularioRegra } from './useFormularioRegra'

vi.mock('@/services/api', () => ({
  apiClient: {
    criarJob: vi.fn<typeof apiClient.criarJob>(),
    consultarJob: vi.fn<typeof apiClient.consultarJob>(),
  },
}))

const criarJob = vi.mocked(apiClient.criarJob)
const consultarJob = vi.mocked(apiClient.consultarJob)

function jobComNucleo(nucleo: Partial<NucleoRegra>) {
  const regra = regraFixture()
  regra.representacao.nucleo = { ...regra.representacao.nucleo, ...nucleo }
  return jobFixture({ regras: [regra] })
}

function preencherFormularioValido() {
  const formulario = useFormularioRegra()
  formulario.formulario.vigenciaInicio = '2025-11'
  formulario.formulario.vigenciaFim = '2025-11'
  formulario.formulario.loja = '13, 21'
  formulario.formulario.marca = '10'
  formulario.formulario.cargo = '100'
  formulario.formulario.percentual = '2,5'
  formulario.formulario.orcamento = '485.000,00'
  return formulario
}

describe('useFormularioRegra', () => {
  afterEach(() => {
    vi.resetAllMocks()
  })

  it('traz o núcleo da regra para os campos e deixa o orçamento em branco', async () => {
    consultarJob.mockResolvedValue(
      jobComNucleo({ loja: ['13', '21'], marca: ['10', '20'], cargo: ['100'], percentual: 0.07 }),
    )
    const formulario = preencherFormularioValido()

    await formulario.preencherComRegraDoJob('job-1')

    expect(formulario.formulario).toMatchObject({
      vigenciaInicio: '2025-11',
      vigenciaFim: '2025-11',
      loja: '13, 21',
      marca: '10, 20',
      cargo: '100',
      percentual: '7',
      orcamento: '',
    })
    expect(consultarJob).toHaveBeenCalledWith('job-1')
  })

  it('preenche a partir da versão mais recente da regra', async () => {
    const anterior = regraFixture(1)
    anterior.representacao.nucleo.loja = ['13']
    const recente = regraFixture(2)
    recente.representacao.nucleo.loja = ['21']
    consultarJob.mockResolvedValue(jobFixture({ regras: [anterior, recente] }))
    const formulario = useFormularioRegra()

    await formulario.preencherComRegraDoJob('job-1')

    expect(formulario.formulario.loja).toBe('21')
  })

  it('descarta a competência que não está entre as opções de vigência', async () => {
    consultarJob.mockResolvedValue(jobComNucleo({ vigencia: { inicio: '2024-01', fim: '2024-02' } }))
    const formulario = useFormularioRegra()

    await formulario.preencherComRegraDoJob('job-1')

    expect(formulario.formulario.vigenciaInicio).toBe('')
    expect(formulario.formulario.vigenciaFim).toBe('')
    expect(formulario.formulario.loja).toBe('13')
  })

  it.each([
    ['a consulta falha', () => consultarJob.mockRejectedValue(new HttpError(404, 'Job não encontrado.'))],
    ['o job não tem regra', () => consultarJob.mockResolvedValue(jobFixture({ regras: [] }))],
  ])('pede o preenchimento manual quando %s', async (_cenario, prepararConsulta) => {
    prepararConsulta()
    const formulario = useFormularioRegra()

    await formulario.preencherComRegraDoJob('job-1')

    expect(formulario.mensagemDoFormulario.value).toBe(
      'Não foi possível carregar a regra selecionada. Preencha os campos manualmente.',
    )
    expect(formulario.formulario.loja).toBe('')
    expect(formulario.preenchendo.value).toBe(false)
  })

  it('marca os campos obrigatórios no próprio formulário', () => {
    const formulario = useFormularioRegra()

    expect(formulario.validarFormulario()).toBe(false)
    expect(formulario.erros.percentual).toBe('Informe o percentual de comissão.')
    expect(formulario.erros.orcamento).toBe('Informe o orçamento disponível.')
  })

  it('envia o núcleo no formato previsto pelo contrato', async () => {
    criarJob.mockResolvedValue(jobCriadoFixture())
    const formulario = preencherFormularioValido()

    await formulario.enviarFormulario()

    expect(criarJob).toHaveBeenCalledWith({
      origem: 'formulario',
      orcamento: 485000,
      conteudo: {
        nucleo: {
          vigencia: { inicio: '2025-11', fim: '2025-11' },
          loja: ['13', '21'],
          marca: ['10'],
          cargo: ['100'],
          percentual: 0.025,
        },
        texto_livre: null,
      },
    })
  })

  it('destaca o campo apontado pela validação da API', async () => {
    criarJob.mockRejectedValue(
      new HttpError(422, 'Percentual de comissionamento: Informe um valor válido.', {
        fieldErrors: [
          { field: 'Percentual de comissionamento', message: 'Informe um valor válido.' },
        ],
      }),
    )
    const formulario = preencherFormularioValido()

    await formulario.enviarFormulario()

    expect(formulario.erros.percentual).toBe('Informe um valor válido.')
  })

  it('devolve o job já em geração, sem etapa de confirmação', async () => {
    const criado = jobCriadoFixture({ status: 'gerando_regra' })
    criarJob.mockResolvedValue(criado)
    const formulario = preencherFormularioValido()

    const resposta = await formulario.enviarFormulario()

    expect(resposta).toEqual(criado)
    expect(criarJob).toHaveBeenCalledOnce()
  })

  it('bloqueia o duplo envio enquanto a criação está em curso', async () => {
    let resolver!: (job: ReturnType<typeof jobCriadoFixture>) => void
    criarJob.mockReturnValue(
      new Promise((resolve) => {
        resolver = resolve
      }),
    )
    const formulario = preencherFormularioValido()

    const primeiro = formulario.enviarFormulario()
    expect(await formulario.enviarFormulario()).toBeUndefined()
    resolver(jobCriadoFixture())
    await primeiro

    expect(criarJob).toHaveBeenCalledOnce()
  })
})
