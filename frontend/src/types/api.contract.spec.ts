import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import type {
  ConfirmarParametrosRequisicao,
  ConteudoSubmissao,
  CriarJobRequisicao,
  RepresentacaoRegra,
  ResultadoSimulacao,
} from './api'

async function desserializarExemplo<T>(caminhoRelativo: string): Promise<T> {
  const diretorioDoArquivo = dirname(fileURLToPath(import.meta.url))
  const caminhoDoExemplo = resolve(
    diretorioDoArquivo,
    '../../../contracts/examples',
    caminhoRelativo,
  )
  const conteudo = await readFile(caminhoDoExemplo, 'utf8')

  return JSON.parse(conteudo) as T
}

describe('tipos do contrato HTTP', () => {
  it('desserializa o conteúdo da submissão em uma requisição de criação de job', async () => {
    const conteudo = await desserializarExemplo<ConteudoSubmissao>(
      'domain/submissao-conteudo.json',
    )
    const requisicao: CriarJobRequisicao = {
      origem: 'formulario',
      competencias: ['2025-11'],
      orcamento: 485000,
      conteudo,
    }

    expect(requisicao.conteudo.nucleo.percentual).toBe(0.03)
    expect(requisicao.conteudo.texto_livre).toContain('MATRIC-422')
  })

  it('desserializa a representação confirmada em uma requisição de parâmetros', async () => {
    const regra = await desserializarExemplo<RepresentacaoRegra>(
      'domain/representacao-regra.json',
    )
    const requisicao: ConfirmarParametrosRequisicao = { regra }

    expect(requisicao.regra.nucleo.percentual).toBe(0.025)
    expect(requisicao.regra.especificacoes).toEqual([])
  })

  it('desserializa o resultado de simulação retornado pelo job', async () => {
    const resultado = await desserializarExemplo<ResultadoSimulacao>(
      'domain/resultado-simulacao.json',
    )

    expect(resultado.totais).not.toBeNull()
    expect(resultado.totais?.orcamento).toBe(485000)
    expect(resultado.assercoes).toHaveLength(3)
  })
})
