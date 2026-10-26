<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import type { RepresentacaoRegra } from '@/types/api'
import {
  formatarReais,
  organizarLinhas,
  rotulosContribuicoes,
} from '@/composables/apresentacaoDetalhamento'
import { nomeDaEntidade } from '@/services/catalogoRh'
const props = defineProps<{
  linhas: ReturnType<typeof organizarLinhas>
  regra?: RepresentacaoRegra
}>()
const pagina = ref(0)
const prefixo = useId()
const abertas = ref(new Set<string>())
const visiveis = computed(() => props.linhas.slice(pagina.value * 25, (pagina.value + 1) * 25))
const rotulos = computed(() => rotulosContribuicoes(props.regra))
watch(
  () => props.linhas,
  () => {
    pagina.value = 0
  },
)
function competencia(valor: string) {
  return valor.split('-').reverse().join('/')
}
type LinhaDaTabela = { competencia: string; matricula: string }
function chave(linha: LinhaDaTabela, referencia: string) {
  return `${linha.competencia}/${linha.matricula}/${referencia}`
}
function idDescricao(linha: LinhaDaTabela, referencia: string) {
  return `${prefixo}-${chave(linha, referencia)}`
}
function alternar(linha: LinhaDaTabela, referencia: string) {
  const alvo = chave(linha, referencia)
  if (abertas.value.has(alvo)) abertas.value.delete(alvo)
  else abertas.value.add(alvo)
}
</script>
<template>
  <div>
    <p
      v-if="!linhas.length"
      role="status"
      class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] p-4"
    >
      Nenhum registro encontrado para os filtros selecionados.
    </p>
    <template v-else>
      <p class="mb-3 text-sm">Comissões por competência e colaborador.</p>
      <div
        class="max-h-[32rem] overflow-auto rounded-lg focus-visible:outline-2"
        tabindex="0"
        role="region"
        aria-label="Comissões por colaborador"
      >
        <table
          class="w-full min-w-[73rem] border-separate border-spacing-x-2 border-spacing-y-3 text-left text-sm"
        >
          <caption class="sr-only">
            Detalhamento das comissões da simulação
          </caption>
          <thead class="sticky top-0 z-10 bg-white text-[#2e1a10]">
            <tr>
              <th scope="col" class="w-28 min-w-28">Competência</th>
              <th scope="col" class="w-32 min-w-32">Matrícula</th>
              <th scope="col">Marca</th>
              <th scope="col">Loja</th>
              <th scope="col">Venda</th>
              <th scope="col">Cargo</th>
              <th scope="col">Comissão atual</th>
              <th scope="col">Comissão simulada</th>
              <th scope="col">Diferença</th>
              <th scope="col">Contribuições da regra</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="linha in visiveis" :key="`${linha.competencia}/${linha.matricula}`">
              <td class="w-28 min-w-28 rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                {{ competencia(linha.competencia) }}
              </td>
              <td class="w-32 min-w-32 rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                {{ linha.matricula }}
              </td>
              <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                {{ nomeDaEntidade('marca', linha.cod_marca) }}
              </td>
              <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                {{ nomeDaEntidade('loja', linha.cod_loja) }}
              </td>
              <td
                class="whitespace-nowrap rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2"
              >
                {{ linha.vendas === undefined ? '—' : formatarReais(linha.vendas) }}
              </td>
              <td class="rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                {{ nomeDaEntidade('cargo', linha.cod_cargo) }}
              </td>
              <td
                class="whitespace-nowrap rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2"
              >
                {{ formatarReais(linha.comissao_baseline) }}
              </td>
              <td
                class="whitespace-nowrap rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2"
              >
                {{ formatarReais(linha.comissao_simulada) }}
              </td>
              <td
                class="whitespace-nowrap rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2"
              >
                {{ formatarReais(linha.diferenca) }}
              </td>
              <td class="min-w-64 rounded-lg border border-[#FFDBCD] bg-[#FFF1EC] px-3 py-2">
                <ul v-if="Object.keys(linha.contribuicoes).length" class="space-y-1">
                  <li v-for="(valor, referencia) in linha.contribuicoes" :key="referencia">
                    {{ rotulos[referencia]?.rotulo ?? 'Condição adicional da regra' }}:
                    {{ formatarReais(valor) }}
                    <template v-if="rotulos[referencia]?.descricao">
                      <button
                        type="button"
                        class="block cursor-pointer text-xs font-semibold text-[#9D4400] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2"
                        :aria-expanded="abertas.has(chave(linha, referencia))"
                        :aria-controls="idDescricao(linha, referencia)"
                        @click="alternar(linha, referencia)"
                      >
                        {{
                          abertas.has(chave(linha, referencia)) ? 'Ocultar descrição' : 'Ver descrição'
                        }}
                      </button>
                      <p
                        v-show="abertas.has(chave(linha, referencia))"
                        :id="idDescricao(linha, referencia)"
                        class="mt-1 text-xs whitespace-pre-wrap"
                      >
                        {{ rotulos[referencia]?.descricao }}
                      </p>
                    </template>
                  </li>
                </ul>
                <span v-else>Sem alteração</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
        <p role="status">Página {{ pagina + 1 }} · {{ linhas.length }} registros</p>
        <nav aria-label="Páginas do relatório" class="flex gap-3">
          <button
            type="button"
            :disabled="pagina === 0"
            class="cursor-pointer rounded-lg border border-[#DFC0B2] px-4 py-2 text-[#9D4400] disabled:cursor-default disabled:opacity-50"
            @click="pagina -= 1"
          >
            Anterior
          </button>
          <button
            type="button"
            :disabled="(pagina + 1) * 25 >= linhas.length"
            class="cursor-pointer rounded-lg border border-[#DFC0B2] px-4 py-2 text-[#9D4400] disabled:cursor-default disabled:opacity-50"
            @click="pagina += 1"
          >
            Próxima
          </button>
        </nav>
      </div>
    </template>
  </div>
</template>
