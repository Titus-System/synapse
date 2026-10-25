import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { rotuloDaRegra } from '@/services/job'
import type { JobResumo } from '@/types/api'

export const tamanhoDaPaginaDeRegras = 12

export interface RegraRecente {
  identificador: string
  rotulo: string
}

function registrarConsulta(
  pagina: number,
  resultado: 'sucesso' | 'falha',
  inicio: number,
  status?: number,
) {
  const registro = {
    timestamp: new Date().toISOString(),
    level: resultado === 'falha' ? 'WARN' : 'INFO',
    message: 'Consulta de regras da barra lateral concluída',
    'service.name': 'synapse-frontend',
    extra: {
      operacao: 'listar_regras_recentes',
      resultado,
      pagina,
      duracao_ms: performance.now() - inicio,
      ...(status == null ? {} : { status_http: status }),
    },
  }
  if (resultado === 'falha') console.warn(JSON.stringify(registro))
  else console.info(JSON.stringify(registro))
}

function paraRegraRecente(resumo: JobResumo): RegraRecente {
  return { identificador: resumo.id, rotulo: rotuloDaRegra(resumo) }
}

export const usarStoreRegrasRecentes = defineStore('regras-recentes', () => {
  const regras = ref<RegraRecente[]>([])
  const total = ref<number | null>(null)
  const falhou = ref(false)
  const consultasEmAndamento = ref(0)

  const carregando = computed(() => consultasEmAndamento.value > 0)
  const todasCarregadas = computed(
    () => total.value !== null && regras.value.length >= total.value,
  )

  async function consultarPagina(pagina: number): Promise<RegraRecente[] | null> {
    consultasEmAndamento.value += 1
    const inicio = performance.now()
    try {
      const resposta = await apiClient.listarJobs({ pagina, tamanho: tamanhoDaPaginaDeRegras })
      registrarConsulta(pagina, 'sucesso', inicio)
      total.value = resposta.total
      falhou.value = false
      return resposta.itens.map(paraRegraRecente)
    } catch (erro) {
      registrarConsulta(pagina, 'falha', inicio, erro instanceof HttpError ? erro.status : undefined)
      falhou.value = true
      return null
    } finally {
      consultasEmAndamento.value -= 1
    }
  }

  // Cada tela monta a própria barra lateral; reconsultar só a primeira página traz as regras
  // criadas desde a última tela sem descartar as páginas que o usuário já rolou.
  async function atualizar(): Promise<void> {
    const primeiraPagina = await consultarPagina(0)
    if (!primeiraPagina) return
    const conhecidas = new Set(regras.value.map((regra) => regra.identificador))
    // Sem nenhuma regra em comum, surgiram regras demais para caber na primeira página e a
    // lista guardada já não continua dela; mantê-la deixaria um buraco no meio.
    const continuaALista =
      conhecidas.size === 0 || primeiraPagina.some((regra) => conhecidas.has(regra.identificador))
    if (!continuaALista) {
      regras.value = primeiraPagina
      return
    }
    const daPrimeiraPagina = new Set(primeiraPagina.map((regra) => regra.identificador))
    regras.value = [
      ...primeiraPagina,
      ...regras.value.filter((regra) => !daPrimeiraPagina.has(regra.identificador)),
    ]
  }

  async function carregarMais(): Promise<void> {
    if (carregando.value || todasCarregadas.value) return
    // Regras novas empurram as antigas para as páginas seguintes; partir do tamanho atual da
    // lista nunca pula uma regra, e as que voltarem repetidas são descartadas.
    const pagina = Math.floor(regras.value.length / tamanhoDaPaginaDeRegras)
    const proximas = await consultarPagina(pagina)
    if (!proximas) return
    const conhecidas = new Set(regras.value.map((regra) => regra.identificador))
    regras.value = [
      ...regras.value,
      ...proximas.filter((regra) => !conhecidas.has(regra.identificador)),
    ]
  }

  return { regras, total, falhou, carregando, todasCarregadas, atualizar, carregarMais }
})
