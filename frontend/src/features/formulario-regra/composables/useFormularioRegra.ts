import { reactive, ref } from 'vue'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { regraMaisRecente } from '@/services/job'
import type { CriarJobRequisicao, JobCriado, NucleoRegra } from '@/types/api'
import type { CampoDoFormulario, FormularioDeRegra, OpcaoDeVigencia } from '../types'

const opcoesDeVigencia: readonly OpcaoDeVigencia[] = [
  { valor: '2025-07', rotulo: 'Julho de 2025' },
  { valor: '2025-08', rotulo: 'Agosto de 2025' },
  { valor: '2025-09', rotulo: 'Setembro de 2025' },
  { valor: '2025-10', rotulo: 'Outubro de 2025' },
  { valor: '2025-11', rotulo: 'Novembro de 2025' },
  { valor: '2025-12', rotulo: 'Dezembro de 2025' },
]

const mensagemDeRegraIndisponivel =
  'Não foi possível carregar a regra selecionada. Preencha os campos manualmente.'

const nomesDeCampo: Record<string, CampoDoFormulario[]> = {
  Vigência: ['vigenciaInicio', 'vigenciaFim'],
  'Início da vigência': ['vigenciaInicio'],
  'Fim da vigência': ['vigenciaFim'],
  Loja: ['loja'],
  Marca: ['marca'],
  Cargo: ['cargo'],
  'Percentual de comissionamento': ['percentual'],
  Orçamento: ['orcamento'],
}

function criarFormularioVazio(): FormularioDeRegra {
  return {
    vigenciaInicio: '',
    vigenciaFim: '',
    loja: '',
    marca: '',
    cargo: '',
    percentual: '',
    orcamento: '',
  }
}

function criarErrosVazios(): Record<CampoDoFormulario, string> {
  return {
    vigenciaInicio: '',
    vigenciaFim: '',
    loja: '',
    marca: '',
    cargo: '',
    percentual: '',
    orcamento: '',
  }
}

function converterEmLista(valor: string): string[] {
  return valor
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function converterPercentual(valor: string): number | undefined {
  const valorNormalizado = valor.trim().replace('%', '').replace(',', '.')
  const numero = Number(valorNormalizado)

  return Number.isFinite(numero) ? numero / 100 : undefined
}

function converterOrcamento(valor: string): number | undefined {
  const valorSemEspacos = valor.trim()
  const valorNormalizado = valorSemEspacos.includes(',')
    ? valorSemEspacos.replace(/\./g, '').replace(',', '.')
    : valorSemEspacos
  const numero = Number(valorNormalizado)

  return Number.isFinite(numero) ? numero : undefined
}

function formatarOrcamento(valor: string): string {
  const numero = converterOrcamento(valor)
  if (numero === undefined) return valor

  return new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numero)
}

function formatarPercentualDoNucleo(valor: number): string {
  // Inverso de converterPercentual. O Intl também descarta o ruído de ponto
  // flutuante: 0.07 * 100 resulta em 7.000000000000001 em JavaScript.
  return new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 4 }).format(valor * 100)
}

function competenciaDisponivel(competencia: string | undefined): string {
  if (!competencia) return ''

  // Uma competência fora das opções deixaria o select mostrando "Selecione uma
  // opção" enquanto a validação considera o campo preenchido.
  return opcoesDeVigencia.some((opcao) => opcao.valor === competencia) ? competencia : ''
}

export function useFormularioRegra() {
  const formulario = reactive(criarFormularioVazio())
  const erros = reactive(criarErrosVazios())
  const mensagemDoFormulario = ref('')
  const enviando = ref(false)
  const preenchendo = ref(false)
  let cicloDePreenchimento = 0

  function limparErros(): void {
    for (const campo of Object.keys(erros) as CampoDoFormulario[]) {
      erros[campo] = ''
    }
  }

  function validarFormulario(): boolean {
    limparErros()

    const obrigatorios: { campo: CampoDoFormulario; mensagem: string }[] = [
      { campo: 'vigenciaInicio', mensagem: 'Informe o início da vigência.' },
      { campo: 'vigenciaFim', mensagem: 'Informe o fim da vigência.' },
      { campo: 'loja', mensagem: 'Informe ao menos um código de loja.' },
      { campo: 'marca', mensagem: 'Informe ao menos um código de marca.' },
      { campo: 'cargo', mensagem: 'Informe ao menos um código de cargo.' },
      { campo: 'percentual', mensagem: 'Informe o percentual de comissão.' },
      { campo: 'orcamento', mensagem: 'Informe o orçamento disponível.' },
    ]

    for (const { campo, mensagem } of obrigatorios) {
      if (!formulario[campo].trim()) erros[campo] = mensagem
    }

    if (formulario.percentual && converterPercentual(formulario.percentual) === undefined) {
      erros.percentual = 'Informe o percentual no formato 2,5.'
    }

    if (formulario.orcamento && converterOrcamento(formulario.orcamento) === undefined) {
      erros.orcamento = 'Informe o orçamento no formato 485.000,00.'
    }

    return Object.values(erros).every((erro) => erro === '')
  }

  function montarRequisicao(): CriarJobRequisicao | undefined {
    const percentual = converterPercentual(formulario.percentual)
    const orcamento = converterOrcamento(formulario.orcamento)
    if (percentual === undefined || orcamento === undefined) return undefined

    return {
      origem: 'formulario',
      orcamento,
      conteudo: {
        nucleo: {
          vigencia: { inicio: formulario.vigenciaInicio, fim: formulario.vigenciaFim },
          loja: converterEmLista(formulario.loja),
          marca: converterEmLista(formulario.marca),
          cargo: converterEmLista(formulario.cargo),
          percentual,
        },
        texto_livre: null,
      },
    }
  }

  function aplicarErrosDaApi(erro: HttpError): void {
    for (const erroDeCampo of erro.fieldErrors) {
      for (const campo of nomesDeCampo[erroDeCampo.field] ?? []) {
        erros[campo] = erroDeCampo.message
      }
    }
  }

  function formatarOrcamentoAoSair(): void {
    formulario.orcamento = formatarOrcamento(formulario.orcamento)
  }

  function preencherComNucleo(nucleo: NucleoRegra): void {
    limparErros()
    formulario.vigenciaInicio = competenciaDisponivel(nucleo.vigencia?.inicio)
    formulario.vigenciaFim = competenciaDisponivel(nucleo.vigencia?.fim)
    formulario.loja = (nucleo.loja ?? []).join(', ')
    formulario.marca = (nucleo.marca ?? []).join(', ')
    formulario.cargo = (nucleo.cargo ?? []).join(', ')
    formulario.percentual =
      nucleo.percentual == null ? '' : formatarPercentualDoNucleo(nucleo.percentual)
    // O orçamento é justamente o que o reprocessamento vem trocar.
    formulario.orcamento = ''
  }

  async function preencherComRegraDoJob(jobId: string): Promise<void> {
    // A consulta anterior não pode sobrescrever um formulário que já pertence a
    // outra regra, ou que o usuário acabou de zerar.
    const ciclo = (cicloDePreenchimento += 1)
    preenchendo.value = true
    mensagemDoFormulario.value = 'Carregando a regra para reprocessamento…'
    try {
      const job = await apiClient.consultarJob(jobId)
      if (ciclo !== cicloDePreenchimento) return

      const regra = regraMaisRecente(job.regras)
      if (!regra) {
        mensagemDoFormulario.value = mensagemDeRegraIndisponivel
        return
      }

      preencherComNucleo(regra.representacao.nucleo)
      mensagemDoFormulario.value =
        'Campos preenchidos com a regra selecionada. Informe o novo orçamento.'
    } catch {
      if (ciclo === cicloDePreenchimento) mensagemDoFormulario.value = mensagemDeRegraIndisponivel
    } finally {
      if (ciclo === cicloDePreenchimento) preenchendo.value = false
    }
  }

  function limparFormulario(): void {
    cicloDePreenchimento += 1
    preenchendo.value = false
    limparErros()
    Object.assign(formulario, criarFormularioVazio())
    mensagemDoFormulario.value = ''
  }

  async function enviarFormulario(): Promise<JobCriado | undefined> {
    if (enviando.value) return undefined
    mensagemDoFormulario.value = ''
    if (!validarFormulario()) {
      mensagemDoFormulario.value = 'Revise os campos destacados antes de continuar.'
      return undefined
    }

    const requisicao = montarRequisicao()
    if (!requisicao) return undefined

    enviando.value = true
    try {
      return await apiClient.criarJob(requisicao)
    } catch (erro) {
      if (erro instanceof HttpError) {
        aplicarErrosDaApi(erro)
        mensagemDoFormulario.value = erro.message
      } else {
        mensagemDoFormulario.value = 'Não foi possível iniciar o processamento. Tente novamente.'
      }
      return undefined
    } finally {
      enviando.value = false
    }
  }

  return {
    opcoesDeVigencia,
    enviando,
    enviarFormulario,
    erros,
    formatarOrcamentoAoSair,
    formulario,
    limparFormulario,
    mensagemDoFormulario,
    preenchendo,
    preencherComRegraDoJob,
    validarFormulario,
  }
}
