import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { apiClient } from '@/services/api'
import { rotuloDaRegra } from '@/services/job'
import type { JobResumo } from '@/types/api'

const tamanhoDaPagina = 100
const quantidadeDeRecentes = 6

export const usarStoreRegrasRecentes = defineStore('regras-recentes', () => {
  const resumos = ref<JobResumo[]>([])
  const carregando = ref(false)
  const erro = ref(false)
  let chamada = 0

  const regrasRecentes = computed(() =>
    resumos.value.slice(0, quantidadeDeRecentes).map((resumo) => ({
      identificador: resumo.id,
      rotulo: rotuloDaRegra(resumo),
    })),
  )
  const quantidadeArquivadas = computed(
    () => resumos.value.filter((resumo) => resumo.status === 'arquivado').length,
  )
  const quantidadeSalvas = computed(() => resumos.value.length - quantidadeArquivadas.value)

  async function carregar(): Promise<void> {
    const numero = ++chamada
    carregando.value = true
    erro.value = false
    try {
      const todos: JobResumo[] = []
      let pagina = 0
      let total = 0
      let itens: JobResumo[] = []
      do {
        const resposta = await apiClient.listarJobs({ pagina, tamanho: tamanhoDaPagina })
        total = resposta.total
        itens = resposta.itens
        todos.push(...itens)
        pagina += 1
      } while (todos.length < total && itens.length > 0)
      if (numero === chamada) resumos.value = todos
    } catch {
      if (numero === chamada) {
        resumos.value = []
        erro.value = true
      }
    } finally {
      if (numero === chamada) carregando.value = false
    }
  }

  function aplicarNome(id: string, nome: string | null | undefined): void {
    resumos.value = resumos.value.map((resumo) => (resumo.id === id ? { ...resumo, nome } : resumo))
  }

  return {
    resumos,
    carregando,
    erro,
    regrasRecentes,
    quantidadeArquivadas,
    quantidadeSalvas,
    carregar,
    aplicarNome,
  }
})