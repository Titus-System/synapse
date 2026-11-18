import { computed, type MaybeRefOrGetter, toValue } from 'vue'
import type {
  ChamadaModeloAuditoria,
  CodigoAuditoria,
  EntradaAuditoria,
  RegistroAuditoria,
  RodadaAuditoria,
  VersaoAuditoria,
} from '../types'

export type ItemConversa =
  | { tipo: 'entrada'; instante: string; entrada: EntradaAuditoria; rodada?: number }
  | { tipo: 'conflitos'; instante: string; rodada: RodadaAuditoria; numero: number }
  | { tipo: 'chamada'; instante: string; chamada: ChamadaModeloAuditoria }
  | { tipo: 'versao'; instante: string; versao: VersaoAuditoria }
  | { tipo: 'codigo'; instante: string; codigo: CodigoAuditoria; versao?: number }

const nosAntesDaVersao = new Set(['extracao_parametros', 'validacao_dominio', 'confirmacao'])

function ordem(item: ItemConversa): number {
  switch (item.tipo) {
    case 'entrada':
      return 0
    case 'conflitos':
      return 1
    case 'chamada':
      return nosAntesDaVersao.has(item.chamada.no) ? 2 : 4
    case 'versao':
      return 3
    case 'codigo':
      return 5
  }
}

function rodadaDaEntrada(entrada: EntradaAuditoria, rodadas: RodadaAuditoria[]): number | undefined {
  if (entrada.finalidade !== 'correcao') return undefined
  const mesmoHorario = rodadas
    .map((rodada, indice) => ({ rodada, indice }))
    .filter(({ rodada }) => rodada.correcao?.enviada_em === entrada.criado_em)
  const confirmada = mesmoHorario.find(
    ({ rodada }) => rodada.correcao?.texto != null && rodada.correcao.texto === entrada.texto,
  )
  const escolhida = confirmada ?? (mesmoHorario.length === 1 ? mesmoHorario[0] : undefined)
  return escolhida ? escolhida.indice + 1 : undefined
}

export function montarConversa(registro: RegistroAuditoria): ItemConversa[] {
  const numeroDaVersao = new Map(registro.versoes.map((v) => [v.id, v.versao]))
  const itens: ItemConversa[] = [
    ...registro.entradas.map((entrada): ItemConversa => ({
      tipo: 'entrada',
      instante: entrada.criado_em,
      entrada,
      rodada: rodadaDaEntrada(entrada, registro.rodadas),
    })),
    ...registro.rodadas.map((rodada, indice): ItemConversa => ({
      tipo: 'conflitos',
      instante: rodada.criada_em,
      rodada,
      numero: indice + 1,
    })),
    ...registro.chamadas_modelo.map((chamada): ItemConversa => ({
      tipo: 'chamada',
      instante: chamada.criado_em,
      chamada,
    })),
    ...registro.versoes.map((versao): ItemConversa => ({
      tipo: 'versao',
      instante: versao.criada_em,
      versao,
    })),
    ...registro.codigos.map((codigo): ItemConversa => ({
      tipo: 'codigo',
      instante: codigo.criado_em,
      codigo,
      versao: numeroDaVersao.get(codigo.regra_id),
    })),
  ]
  // sort é estável: empate total preserva a ordem de inserção acima.
  return itens
    .map((item, posicao) => ({ item, posicao }))
    .sort(
      (a, b) =>
        Date.parse(a.item.instante) - Date.parse(b.item.instante) ||
        ordem(a.item) - ordem(b.item) ||
        a.posicao - b.posicao,
    )
    .map(({ item }) => item)
}

export function useConversaAuditoria(registro: MaybeRefOrGetter<RegistroAuditoria>) {
  const itens = computed(() => montarConversa(toValue(registro)))
  const codigos = computed(() =>
    toValue(registro).codigos.map((codigo) => ({
      codigo,
      versao: toValue(registro).versoes.find((v) => v.id === codigo.regra_id),
      chamada: toValue(registro).chamadas_modelo.find((c) => c.id === codigo.prompt_id),
    })),
  )
  return { itens, codigos }
}