import { onBeforeUnmount, ref } from 'vue'
import { registrarEntrada } from '../services/observabilidade'

const LIMITE_BYTES = 5 * 1024 * 1024
const LIMITE_MS = 180_000
const formatos = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']

export function useGravacao() {
  const gravando = ref(false)
  const solicitando = ref(false)
  const audio = ref<Blob | null>(null)
  const url = ref('')
  const erro = ref('')
  let recorder: MediaRecorder | undefined
  let stream: MediaStream | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let descartada = false
  let inicio = 0

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
    if (recorder?.state === 'recording') recorder.stop()
    liberar()
  }
  async function iniciar() {
    if (solicitando.value || gravando.value) return
    erro.value = ''
    inicio = performance.now()
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      erro.value = 'Este navegador não permite gravar áudio. Use a entrada por texto.'
      registrarEntrada('gravar_audio', 'falha', inicio)
      return
    }
    solicitando.value = true
    limparAudio()
    try {
      const mimeType = formatos.find((tipo) => MediaRecorder.isTypeSupported(tipo))
      if (!mimeType) throw new Error('formato_indisponivel')
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (descartada) {
        liberar()
        return
      }
      recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64000 })
      const partes: Blob[] = []
      let tamanho = 0
      recorder.ondataavailable = (evento) => {
        tamanho += evento.data.size
        if (tamanho > LIMITE_BYTES) {
          erro.value = 'A gravação ficou grande demais. Grave um áudio mais curto.'
          parar()
        } else partes.push(evento.data)
      }
      recorder.onerror = () => {
        erro.value = 'Não foi possível gravar. Confira o microfone e tente novamente.'
        parar()
      }
      recorder.onstop = () => {
        gravando.value = false
        liberar()
        if (!descartada && !erro.value) {
          const blob = new Blob(partes, { type: mimeType })
          if (blob.size) {
            audio.value = blob
            url.value = URL.createObjectURL(blob)
          } else erro.value = 'A gravação está vazia. Grave novamente.'
        }
        registrarEntrada(
          'gravar_audio',
          descartada ? 'cancelado' : erro.value ? 'falha' : 'sucesso',
          inicio,
        )
      }
      recorder.start(1000)
      gravando.value = true
      timer = setTimeout(parar, LIMITE_MS)
    } catch {
      liberar()
      erro.value = 'Não foi possível acessar o microfone. Confira a permissão ou envie por texto.'
      registrarEntrada('gravar_audio', descartada ? 'cancelado' : 'falha', inicio)
    } finally {
      solicitando.value = false
    }
  }
  onBeforeUnmount(() => {
    descartada = true
    parar()
    limparAudio()
  })
  return { gravando, solicitando, audio, url, erro, iniciar, parar }
}
