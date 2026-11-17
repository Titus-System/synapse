import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { HttpError } from '@/services/http'
import { regraMaisRecente } from '@/services/job'
import { transformarRegra } from '@/composables/transformarRegra'
import type { JobResumo } from '@/types/api'
import type { TipoDeHistorico } from '../types'
import { consultarRegraDoHistorico, listarPaginaDoHistorico } from '../services/historicoJobs.api'

export interface CartaoHistorico {
  resumo: JobResumo
  contexto: string
  falhou: boolean
}

function registrarFalha(
  operacao: 'listar_regras_salvas' | 'listar_regras_arquivadas' | 'consultar_regra_historico',
  erro: unknown,
  inicio: number,
  jobId?: string,
) {
  console.warn(
    JSON.stringify({
      timestamp: new Date().toISOString(),
      level: 'WARN',
      message: 'Falha na consulta do repositório de regras',
      'service.name': 'synapse-frontend',
      ...(jobId ? { job_id: jobId } : {}),
      extra: {
        operacao,
        resultado: 'falha',
        duracao_ms: performance.now() - inicio,
        ...(erro instanceof HttpError ? { status_http: erro.status } : {}),
      },
    }),
  )
}

export function useHistoricoPaginado(tipo: Ref<TipoDeHistorico>) {
  const tamanho = 5
  const pagina = ref(0)
  const carregando = ref(false)
  const erro = ref('')
  const cartoes = ref<CartaoHistorico[]>([])
  const totais = ref<Record<TipoDeHistorico, number | undefined>>({
    salvas: undefined,
    arquivadas: undefined,
  })
  let controle: AbortController | undefined
  let versao = 0
  const total = computed(() => totais.value[tipo.value] ?? 0)
  const paginas = computed(() => Math.max(1, Math.ceil(total.value / tamanho)))
  const primeira = computed(() => (cartoes.value.length ? pagina.value * tamanho + 1 : 0))
  const ultima = computed(() => pagina.value * tamanho + cartoes.value.length)
  const numeros = computed(() => {
    const inicio = Math.max(0, Math.min(pagina.value - 2, paginas.value - 5))
    return Array.from({ length: Math.min(5, paginas.value) }, (_, i) => inicio + i)
  })

  async function listar(
    situacao: TipoDeHistorico,
    numero: number,
    quantidade: number,
    signal: AbortSignal,
  ) {
    const inicio = performance.now()
    try {
      return await listarPaginaDoHistorico(situacao, numero, quantidade, signal)
    } catch (falha) {
      if (!signal.aborted)
        registrarFalha(
          situacao === 'salvas' ? 'listar_regras_salvas' : 'listar_regras_arquivadas',
          falha,
          inicio,
        )
      throw falha
    }
  }

  async function carregarCartao(resumo: JobResumo, signal: AbortSignal): Promise<CartaoHistorico> {
    const inicio = performance.now()
    try {
      const job = await consultarRegraDoHistorico(resumo.id, signal)
      const regra = regraMaisRecente(job.regras)
      const formato = regra ? transformarRegra(regra.representacao) : undefined
      return {
        resumo: { ...resumo, nome: job.nome ?? resumo.nome },
        falhou: false,
        contexto: formato
          ? [
              ...formato.se.map((linha) => `SE ${linha}`),
              ...formato.entao.map((linha) => `ENTÃO ${linha}`),
            ].join('\n')
          : '',
      }
    } catch (falha) {
      if (!signal.aborted) registrarFalha('consultar_regra_historico', falha, inicio, resumo.id)
      return { resumo, falhou: true, contexto: '' }
    }
  }

  async function carregar(numero = pagina.value): Promise<void> {
    controle?.abort()
    const atual = ++versao
    const signal = (controle = new AbortController()).signal
    const situacao = tipo.value
    const outra = situacao === 'salvas' ? 'arquivadas' : 'salvas'
    pagina.value = numero
    carregando.value = true
    erro.value = ''
    cartoes.value = []
    const [lista, quantidade] = await Promise.allSettled([
      listar(situacao, numero, tamanho, signal),
      listar(outra, 0, 1, signal),
    ])
    if (atual !== versao || signal.aborted) return
    totais.value[outra] = quantidade.status === 'fulfilled' ? quantidade.value.total : undefined
    if (lista.status === 'rejected') {
      totais.value[situacao] = undefined
      erro.value = 'Não foi possível carregar as regras. Tente novamente.'
      carregando.value = false
      return
    }
    totais.value[situacao] = lista.value.total
    if (numero >= paginas.value && lista.value.itens.length === 0) {
      await carregar(Math.max(0, paginas.value - 1))
      return
    }
    const resultado = await Promise.all(
      lista.value.itens.map((resumo) => carregarCartao(resumo, signal)),
    )
    if (atual !== versao || signal.aborted) return
    cartoes.value = resultado
    carregando.value = false
  }

  function irParaPagina(numero: number): void {
    if (carregando.value || numero < 0 || numero >= paginas.value || numero === pagina.value) return
    void carregar(numero)
  }

  watch(
    tipo,
    () => {
      void carregar(0)
    },
    { immediate: true },
  )
  onBeforeUnmount(() => {
    versao++
    controle?.abort()
  })
  return {
    tamanho,
    pagina,
    carregando,
    erro,
    cartoes,
    totais,
    total,
    paginas,
    numeros,
    primeira,
    ultima,
    carregar,
    irParaPagina,
  }
}
