import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { regraMaisRecente } from '@/services/job'

import type {
  ConfirmarParametrosRequisicao,
  ConteudoSubmissao,
  CriarJobRequisicao,
  EventoEtapa,
  Job,
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

  it('desserializa os conflitos da pausa para correção no evento de etapa', async () => {
    const evento = await desserializarExemplo<EventoEtapa>('events/etapa-alterada-conflitos.json')

    expect(evento.status).toBe('aguardando_correcao')
    expect(evento.conflitos).toHaveLength(2)
    expect(evento.conflitos?.[1]?.elementos).toEqual(['nucleo.loja', 'elem.2'])
  })

  it('aceita o job de uma descrição em texto ainda sem regra extraída', () => {
    const job: Job = {
      id: 'a2c4e6f8-0b1d-4e3f-8a5c-7e9b1d3f5a70',
      status: 'gerando_regra',
      origem: 'texto',
      competencias: ['2025-11'],
      orcamento: 485000,
      criado_em: '2025-11-24T15:10:00Z',
      submissao_id: 'e1f3a5c7-9b2d-4f6e-8a0c-2d4f6a8c0e19',
      regras: [],
    }

    expect(regraMaisRecente(job.regras)).toBeUndefined()
  })
})
