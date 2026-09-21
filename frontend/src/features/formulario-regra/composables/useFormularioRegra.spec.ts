import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import type { CriarJobRequisicao, Job } from '@/types/api'
import { useFormularioRegra } from './useFormularioRegra'

vi.mock('@/services/api', () => ({
  apiClient: {
    criarJob: vi.fn<(requisicao: CriarJobRequisicao, sinal?: AbortSignal) => Promise<Job>>(),
  },
}))

const criarJob = vi.mocked(apiClient.criarJob)

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

  it('marca os campos obrigatórios no próprio formulário', () => {
    const formulario = useFormularioRegra()

    expect(formulario.validarFormulario()).toBe(false)
    expect(formulario.erros.percentual).toBe('Informe o percentual de comissão.')
    expect(formulario.erros.orcamento).toBe('Informe o orçamento disponível.')
  })

  it('envia o núcleo no formato previsto pelo contrato', async () => {
    criarJob.mockResolvedValue({ id: 'job-1' } as never)
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
        fieldErrors: [{ field: 'Percentual de comissionamento', message: 'Informe um valor válido.' }],
      }),
    )
    const formulario = preencherFormularioValido()

    await formulario.enviarFormulario()

    expect(formulario.erros.percentual).toBe('Informe um valor válido.')
  })
})
