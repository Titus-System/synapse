import { computed, onBeforeUnmount, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { apiClient } from '@/services/api'
import { HttpError } from '@/services/http'
import { abrirAcompanhamentoJob } from '@/services/jobEvents'
import { registrarVoz, type CodigoVoz } from '@/observability/vozLogging'
import type { Job } from '@/types/api'
import { enviarCorrecaoTexto, enviarCorrecaoVoz, listarRodadas } from '../services/correcao.api'
import type { Rodada } from '../types'

function codigoSeguro(erro: unknown): CodigoVoz {
  if (!(erro instanceof HttpError)) return 'falha_servico'
  switch (erro.code) {
    case 'audio_invalido':
    case 'audio_muito_grande':
    case 'estado_invalido':
    case 'requisicao_invalida':
    case 'nao_autenticado':
    case 'sem_permissao':
    case 'job_nao_encontrado':
      return erro.code
    default:
      return erro.status === 0 ? 'falha_rede' : 'falha_servico'
  }
}

export function useCorrecao(jobId: MaybeRefOrGetter<string>) {
  const rodadas = ref<Rodada[]>([])
  const job = ref<Job | null>(null)
  const texto = ref('')
  const carregando = ref(false)
  const enviando = ref(false)
  const erroLeitura = ref('')
  const erroEnvio = ref('')
  const ultima = computed(() => rodadas.value[rodadas.value.length - 1])
  const processando = computed(() =>
    ['em_transcricao', 'em_reextracao'].includes(ultima.value?.estado ?? ''),
  )
  const habilitada = computed(
    () =>
      !!job.value &&
      !carregando.value &&
      !enviando.value &&
      !erroLeitura.value &&
      job.value.status === 'aguardando_confirmacao_parametros' &&
      ultima.value?.estado === 'pendente',
  )
  const podeEnviar = computed(
    () => habilitada.value && !!texto.value.trim() && texto.value.length <= 4000,
  )
  const encerrado = computed(() =>
    ['cancelado', 'arquivado', 'erro'].includes(job.value?.status ?? ''),
  )
  const seguirProcessamento = computed(
    () =>
      !!job.value &&
      !carregando.value &&
      !erroLeitura.value &&
      !encerrado.value &&
      !rodadas.value.some((rodada) =>
        ['pendente', 'em_transcricao', 'em_reextracao'].includes(rodada.estado),
      ),
  )
  let sessao:
    | {
        id: string
        controlador: AbortController
        fechar: () => void
        revisao: number
        lendo: boolean
        reler: boolean
        timer?: ReturnType<typeof setTimeout>
        cancelarEnvio?: () => void
      }
    | undefined

  function parar() {
    if (!sessao) return
    sessao.cancelarEnvio?.()
    sessao.controlador.abort()
    sessao.fechar()
    clearTimeout(sessao.timer)
    sessao = undefined
  }
  async function atualizar() {
    const atual = sessao
    if (!atual) return
    if (atual.lendo) {
      atual.reler = true
      return
    }
    atual.lendo = true
    atual.reler = false
    clearTimeout(atual.timer)
    const revisao = atual.revisao
    const inicio = performance.now()
    try {
      const [resposta, detalhe] = await Promise.all([
        listarRodadas(atual.id, atual.controlador.signal),
        apiClient.consultarJob(atual.id, atual.controlador.signal),
      ])
      if (sessao !== atual || revisao !== atual.revisao) return
      rodadas.value = resposta
      job.value = detalhe
      erroLeitura.value = ''
      registrarVoz('ler_rodadas', 'ok', inicio, atual.id)
    } catch (erro) {
      if (sessao !== atual || revisao !== atual.revisao) return
      erroLeitura.value = 'Não foi possível atualizar a conversa. Tente novamente.'
      registrarVoz('ler_rodadas', codigoSeguro(erro), inicio, atual.id)
    } finally {
      atual.lendo = false
      if (sessao === atual) {
        if (!atual.reler) carregando.value = false
        if (atual.reler) void atualizar()
        // A transcrição concluída não publica SSE; a leitura também cobre eventos perdidos.
        else if (processando.value) atual.timer = setTimeout(() => void atualizar(), 3000)
      }
    }
  }
  async function enviar(audio?: Blob) {
    const atual = sessao
    if (!atual || !habilitada.value || (audio ? !audio.size : !podeEnviar.value)) return
    enviando.value = true
    erroEnvio.value = ''
    atual.revisao += 1
    const inicio = performance.now()
    const operacao = audio ? 'enviar_correcao_voz' : 'enviar_correcao'
    let registrado = false
    const registrar = (codigo: CodigoVoz) => {
      if (registrado) return
      registrado = true
      registrarVoz(operacao, codigo, inicio, atual.id)
    }
    atual.cancelarEnvio = () => registrar('cancelado')
    try {
      const resposta = audio
        ? await enviarCorrecaoVoz(atual.id, audio, atual.controlador.signal)
        : await enviarCorrecaoTexto(atual.id, texto.value.trim(), atual.controlador.signal)
      if (sessao !== atual) return
      atual.revisao += 1
      rodadas.value = rodadas.value.map((rodada) =>
        rodada.id === resposta.rodada.id ? resposta.rodada : rodada,
      )
      if (!rodadas.value.some((rodada) => rodada.id === resposta.rodada.id))
        rodadas.value.push(resposta.rodada)
      if (job.value) job.value.status = resposta.job.status
      if (!audio) texto.value = ''
      registrar('ok')
      clearTimeout(atual.timer)
      atual.timer = setTimeout(() => void atualizar(), 3000)
    } catch (erro) {
      if (sessao !== atual) return
      const codigo = codigoSeguro(erro)
      registrar(codigo)
      erroEnvio.value =
        codigo === 'audio_muito_grande'
          ? 'A gravação ficou grande demais. Grave um áudio mais curto ou envie por texto.'
          : codigo === 'audio_invalido'
            ? 'Não foi possível usar o áudio. Grave novamente ou envie por texto.'
            : codigo === 'estado_invalido'
              ? 'O envio não está disponível. A conversa será atualizada; você pode tentar por texto quando a entrada for liberada.'
              : 'Não foi possível enviar a correção. Tente novamente por voz ou por texto.'
      carregando.value = true
      // O servidor pode ter aceitado o envio antes de a conexão cair.
      await atualizar()
    } finally {
      atual.cancelarEnvio = undefined
      if (sessao === atual) enviando.value = false
    }
  }

  watch(
    () => toValue(jobId),
    (id) => {
      parar()
      rodadas.value = []
      job.value = null
      texto.value = ''
      enviando.value = false
      erroEnvio.value = ''
      erroLeitura.value = ''
      carregando.value = !!id
      if (!id) return
      const atual = {
        id,
        controlador: new AbortController(),
        fechar: () => {},
        revisao: 0,
        lendo: false,
        reler: false,
      }
      sessao = atual
      const reconciliar = () => {
        if (sessao === atual) void atualizar()
      }
      let estadoConexao = ''
      atual.fechar = abrirAcompanhamentoJob(id, {
        onEstado: reconciliar,
        onEtapa: reconciliar,
        onResultado: reconciliar,
        onReconciliar: reconciliar,
        onStatusConexao: (estado) => {
          if (sessao !== atual || estado === estadoConexao) return
          estadoConexao = estado
          if (estado !== 'conectando')
            registrarVoz(
              'conexao_correcao',
              estado === 'aberta' ? 'ok' : 'reconectando',
              performance.now(),
              id,
            )
        },
      }).fechar
      void atualizar()
    },
    { immediate: true },
  )
  onBeforeUnmount(parar)
  return {
    rodadas,
    job,
    texto,
    carregando,
    enviando,
    erroLeitura,
    erroEnvio,
    habilitada,
    podeEnviar,
    encerrado,
    seguirProcessamento,
    atualizar,
    enviar,
  }
}
