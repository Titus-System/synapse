import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { apiClient } from '@/services/api'
import { HttpError, mensagemDoCodigo } from '@/services/http'

export const limiteDoNome = 100

export function contarCaracteres(texto: string): number {
  return [...texto].length
}

export const usarStoreRenomearRegra = defineStore('renomear-regra', () => {
  const idEmEdicao = ref<string | null>(null)
  const nomeInicial = ref('')
  const texto = ref('')
  const enviando = ref(false)
  const erro = ref('')
  const nomes = ref<Record<string, string>>({})

  const textoAparado = computed(() => texto.value.trim())
  const tamanho = computed(() => contarCaracteres(textoAparado.value))
  const mensagemDeValidacao = computed(() => {
    if (idEmEdicao.value === null) return ''
    if (textoAparado.value === '') return 'Informe um nome para a regra.'
    if (tamanho.value > limiteDoNome) return 'O nome deve ter no máximo 100 caracteres.'
    return ''
  })
  const podeConfirmar = computed(
    () =>
      idEmEdicao.value !== null &&
      !enviando.value &&
      mensagemDeValidacao.value === '' &&
      textoAparado.value !== nomeInicial.value.trim(),
  )

  // As listas já carregadas guardam o nome antigo; o nome devolvido pela api vale sobre elas.
  function rotuloExibido(id: string, rotulo: string): string {
    return nomes.value[id] ?? rotulo
  }

  function iniciar(id: string, rotuloAtual: string): void {
    if (enviando.value) return
    idEmEdicao.value = id
    nomeInicial.value = rotuloAtual
    texto.value = rotuloAtual
    erro.value = ''
  }

  function cancelar(): void {
    if (enviando.value) return
    idEmEdicao.value = null
    erro.value = ''
  }

  async function confirmar(): Promise<boolean> {
    const id = idEmEdicao.value
    if (id === null || !podeConfirmar.value) return false
    enviando.value = true
    erro.value = ''
    try {
      const atualizado = await apiClient.renomearJob(id, { nome: texto.value })
      if (atualizado.nome) nomes.value = { ...nomes.value, [id]: atualizado.nome }
      idEmEdicao.value = null
      return true
    } catch (falha) {
      erro.value =
        falha instanceof HttpError
          ? (falha.fieldErrors.length === 0 ? mensagemDoCodigo(falha.code) : undefined) ??
            falha.message
          : 'Não foi possível renomear a regra. Tente novamente.'
      return false
    } finally {
      enviando.value = false
    }
  }

  return {
    idEmEdicao, texto, enviando, erro, tamanho, nomes,
    mensagemDeValidacao, podeConfirmar,
    rotuloExibido, iniciar, cancelar, confirmar,
  }
})