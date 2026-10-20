import { onBeforeUnmount, ref } from 'vue'
import { registrarVoz, type CodigoVoz } from '@/observability/vozLogging'

const LIMITE_BYTES = 5 * 1024 * 1024
const LIMITE_MS = 180_000
const formatos = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']
const mensagens: Partial<Record<CodigoVoz, string>> = {
  sem_suporte: 'Este navegador não permite gravar áudio. Use a entrada por texto.',
  permissao_negada: 'Permissão do microfone negada. Autorize o acesso ou envie por texto.',
  sem_microfone: 'Nenhum microfone encontrado. Conecte um microfone ou envie por texto.',
  microfone_indisponivel:
    'Não foi possível acessar o microfone. Confira a permissão ou envie por texto.',
  audio_vazio: 'A gravação está vazia. Grave novamente.',
  audio_muito_grande: 'A gravação ficou grande demais. Grave um áudio mais curto.',
  falha_gravacao: 'Não foi possível gravar. Confira o microfone e tente novamente.',
}

export function useGravacao(obterJobId: () => string | undefined = () => undefined) {
  const gravando = ref(false)
  const solicitando = ref(false)
  const finalizando = ref(false)
  const audio = ref<Blob | null>(null)
  const url = ref('')
  const erro = ref('')
  let recorder: MediaRecorder | undefined
  let stream: MediaStream | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let ciclo = 0
  let encerrada = false
  let concluir: ((codigo: CodigoVoz) => void) | undefined

  function liberar() {
    clearTimeout(timer)
    stream?.getTracks().forEach((track) => track.stop())
    stream = undefined
  }
  function limparAudio() {
    if (url.value) URL.revokeObjectURL(url.value)
    url.value = ''
    audio.value = null
  }
  function parar() {
    if (recorder?.state === 'recording') {
      finalizando.value = true
      recorder.stop()
    }
    liberar()
  }
  function descartar() {
    ciclo += 1
    concluir?.('cancelado')
    concluir = undefined
    parar()
    recorder = undefined
    gravando.value = false
    solicitando.value = false
    finalizando.value = false
    limparAudio()
    erro.value = ''
  }
  async function iniciar() {
    if (encerrada || solicitando.value || gravando.value || finalizando.value) return
    descartar()
    const atual = ciclo
    const inicio = performance.now()
    const jobId = obterJobId()
    let terminou = false
    const registrar = (codigo: CodigoVoz) => {
      if (terminou) return
      terminou = true
      registrarVoz('gravar_audio', codigo, inicio, jobId)
    }
    concluir = registrar
    const falhar = (codigo: CodigoVoz) => {
      erro.value = mensagens[codigo] ?? mensagens.falha_gravacao!
      registrar(codigo)
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      falhar('sem_suporte')
      return
    }
    solicitando.value = true
    try {
      const mimeType = formatos.find((tipo) => MediaRecorder.isTypeSupported(tipo))
      if (!mimeType) {
        falhar('sem_suporte')
        return
      }
      const recebido = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (atual !== ciclo) {
        recebido.getTracks().forEach((track) => track.stop())
        return
      }
      stream = recebido
      const captura = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64000 })
      recorder = captura
      const partes: Blob[] = []
      let tamanho = 0
      captura.ondataavailable = (evento) => {
        if (atual !== ciclo || erro.value) return
        tamanho += evento.data.size
        if (tamanho > LIMITE_BYTES) {
          falhar('audio_muito_grande')
          parar()
        } else partes.push(evento.data)
      }
      captura.onerror = () => {
        if (atual !== ciclo) return
        falhar('falha_gravacao')
        parar()
      }
      captura.onstop = () => {
        if (atual !== ciclo) return
        gravando.value = false
        finalizando.value = false
        liberar()
        if (!erro.value) {
          const blob = new Blob(partes, { type: mimeType })
          if (blob.size) {
            audio.value = blob
            url.value = URL.createObjectURL(blob)
            registrar('ok')
          } else falhar('audio_vazio')
        }
      }
      captura.start(1000)
      gravando.value = true
      timer = setTimeout(parar, LIMITE_MS)
    } catch (falha) {
      if (atual !== ciclo) return
      liberar()
      const nome = falha instanceof Error || falha instanceof DOMException ? falha.name : ''
      falhar(
        nome === 'NotAllowedError'
          ? 'permissao_negada'
          : nome === 'NotFoundError'
            ? 'sem_microfone'
            : 'microfone_indisponivel',
      )
    } finally {
      if (atual === ciclo) solicitando.value = false
    }
  }
  onBeforeUnmount(() => {
    encerrada = true
    descartar()
  })
  return { gravando, solicitando, finalizando, audio, url, erro, iniciar, parar, descartar }
}
