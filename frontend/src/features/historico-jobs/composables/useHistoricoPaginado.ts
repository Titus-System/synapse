import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { HttpError } from '@/services/http'
import { regraMaisRecente } from '@/services/job'
import { transformarRegra } from '@/composables/transformarRegra'
import type { JobResumo } from '@/types/api'
import type { TipoDeHistorico } from '../types'
import {
  consultarRegraDoHistorico,
  listarHistoricoCompleto,
  listarPaginaDoHistorico,
} from '../services/historicoJobs.api'
import {
  competenciasDisponiveis,
  correspondeABusca,
  filtrando,
  filtrarEOrdenar,
  filtrosIniciais,
  normalizarTexto,
  rotuloDaRegra,
  type FiltrosDoHistorico,
} from './filtrosDoHistorico'

export interface CartaoHistorico {
  resumo: JobResumo
  contexto: string
  falhou: boolean
}

interface DetalheDaRegra {
  nome?: string | null
  contexto: string
  falhou: boolean
}

// Consultas de detalhe simultâneas ao buscar na lógica de todas as regras da lista.
const CONSULTAS_SIMULTANEAS = 4

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
  const filtros = ref<FiltrosDoHistorico>(filtrosIniciais())
  const resumos = ref<JobResumo[]>([])
  const detalhes = ref<Record<string, DetalheDaRegra>>({})
  const totais = ref<Record<TipoDeHistorico, number | undefined>>({
    salvas: undefined,
    arquivadas: undefined,
  })
  const pendentes = new Set<string>()
  let controle: AbortController | undefined
  let versao = 0

  const nomeDe = (resumo: JobResumo) => detalhes.value[resumo.id]?.nome ?? resumo.nome
  const termo = computed(() => normalizarTexto(filtros.value.busca.trim()))
  const semBusca = computed(() => filtrarEOrdenar(resumos.value, filtros.value, nomeDe))
  const encontrados = computed(() =>
    termo.value
      ? semBusca.value.filter((resumo) =>
          correspondeABusca(
            [rotuloDaRegra(resumo.id, nomeDe(resumo)), detalhes.value[resumo.id]?.contexto ?? ''],
            termo.value,
          ),
        )
      : semBusca.value,
  )
  const visiveis = computed(() =>
    encontrados.value.slice(pagina.value * tamanho, (pagina.value + 1) * tamanho),
  )
  const cartoes = computed<CartaoHistorico[]>(() =>
    visiveis.value.map((resumo) => ({
      resumo: { ...resumo, nome: nomeDe(resumo) },
      contexto: detalhes.value[resumo.id]?.contexto ?? '',
      falhou: detalhes.value[resumo.id]?.falhou ?? false,
    })),
  )
  const total = computed(() => encontrados.value.length)
  const possuiRegras = computed(() => resumos.value.length > 0)
  const filtrosAtivos = computed(() => filtrando(filtros.value))
  const competencias = computed(() => competenciasDisponiveis(resumos.value))
  const buscandoNaLogica = computed(
    () => termo.value !== '' && semBusca.value.some((resumo) => !detalhes.value[resumo.id]),
  )
  const paginas = computed(() => Math.max(1, Math.ceil(total.value / tamanho)))
  const primeira = computed(() => (cartoes.value.length ? pagina.value * tamanho + 1 : 0))
  const ultima = computed(() => pagina.value * tamanho + cartoes.value.length)
  const numeros = computed(() => {
    const inicio = Math.max(0, Math.min(pagina.value - 2, paginas.value - 5))
    return Array.from({ length: Math.min(5, paginas.value) }, (_, i) => inicio + i)
  })

  async function listar<T>(
    situacao: TipoDeHistorico,
    consulta: () => Promise<T>,
    signal: AbortSignal,
  ) {
    const inicio = performance.now()
    try {
      return await consulta()
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

  async function consultarDetalhe(resumo: JobResumo, signal: AbortSignal): Promise<DetalheDaRegra> {
    const inicio = performance.now()
    try {
      const job = await consultarRegraDoHistorico(resumo.id, signal)
      const regra = regraMaisRecente(job.regras)
      const formato = regra ? transformarRegra(regra.representacao) : undefined
      return {
        nome: job.nome ?? resumo.nome,
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
      return { nome: resumo.nome, falhou: true, contexto: '' }
    }
  }

  // Cada regra é consultada uma vez por carga da lista; a resposta fica guardada para a
  // paginação, a ordenação por nome e a busca na lógica.
  async function garantirDetalhes(lista: JobResumo[]): Promise<void> {
    if (!controle) return
    const signal = controle.signal
    const atual = versao
    const faltando = lista.filter(
      (resumo) => !detalhes.value[resumo.id] && !pendentes.has(resumo.id),
    )
    faltando.forEach((resumo) => pendentes.add(resumo.id))
    let proximo = 0
    async function consultarEmSequencia() {
      while (proximo < faltando.length) {
        const resumo = faltando[proximo++]!
        const detalhe = await consultarDetalhe(resumo, signal)
        if (atual !== versao || signal.aborted) return
        pendentes.delete(resumo.id)
        detalhes.value[resumo.id] = detalhe
      }
    }
    await Promise.all(
      Array.from(
        { length: Math.min(CONSULTAS_SIMULTANEAS, faltando.length) },
        consultarEmSequencia,
      ),
    )
  }

  async function carregar(): Promise<void> {
    controle?.abort()
    const atual = ++versao
    const signal = (controle = new AbortController()).signal
    const situacao = tipo.value
    const outra = situacao === 'salvas' ? 'arquivadas' : 'salvas'
    pendentes.clear()
    pagina.value = 0
    carregando.value = true
    erro.value = ''
    resumos.value = []
    detalhes.value = {}
    const [lista, quantidade] = await Promise.allSettled([
      listar(situacao, () => listarHistoricoCompleto(situacao, signal), signal),
      listar(outra, () => listarPaginaDoHistorico(outra, 0, 1, signal), signal),
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
    resumos.value = lista.value.itens
    await garantirDetalhes(visiveis.value)
    if (atual !== versao || signal.aborted) return
    carregando.value = false
  }

  function irParaPagina(numero: number): void {
    if (carregando.value || numero < 0 || numero >= paginas.value || numero === pagina.value) return
    pagina.value = numero
  }

  function limparFiltros(): void {
    filtros.value = filtrosIniciais()
  }

  watch(
    filtros,
    () => {
      pagina.value = 0
    },
    { deep: true },
  )
  // A busca pode encolher a lista enquanto os detalhes chegam.
  watch(paginas, (quantidade) => {
    if (pagina.value >= quantidade) pagina.value = quantidade - 1
  })
  watch(visiveis, (lista) => {
    if (!carregando.value) void garantirDetalhes(lista)
  })
  // Buscar na lógica exige o detalhe de toda regra que passou pelos outros filtros.
  watch([termo, semBusca], ([atual, lista]) => {
    if (atual) void garantirDetalhes(lista)
  })
  watch(
    tipo,
    () => {
      filtros.value = filtrosIniciais()
      void carregar()
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
    filtros,
    cartoes,
    totais,
    total,
    paginas,
    numeros,
    primeira,
    ultima,
    possuiRegras,
    filtrosAtivos,
    competencias,
    buscandoNaLogica,
    carregar,
    irParaPagina,
    limparFiltros,
  }
}
