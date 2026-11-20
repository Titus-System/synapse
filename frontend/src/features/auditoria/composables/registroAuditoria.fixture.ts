import type { RegistroAuditoria } from '../types'
export const registroExemplo = {
  "job": {
    "id": "00000000-0000-4000-8000-000000000001",
    "nome": "Comissão de novembro",
    "status": "liberado",
    "origem": "voz",
    "competencias": [
      "2025-11"
    ],
    "orcamento": 600000,
    "meta_venda": 28000000,
    "criado_em": "2025-11-28T14:00:00Z",
    "finalizado_em": "2025-11-28T14:18:00Z",
    "usuario": {
      "login": "rh.exemplo",
      "nome": "Profissional de RH"
    },
    "iniciado_em": "2025-11-28T14:01:00Z"
  },
  "entradas": [
    {
      "id": "00000000-0000-4000-8000-000000000002",
      "tipo": "voz",
      "finalidade": "entrada_inicial",
      "texto": "Comissão em novembro de 2025 na loja 13, marcas 10 e 20, cargos 100 e 300. Orçamento de 600 mil e meta de venda de 28 milhões.",
      "formato": "ogg",
      "criado_em": "2025-11-28T14:00:00Z",
      "transcrito_em": "2025-11-28T14:01:00Z"
    },
    {
      "id": "00000000-0000-4000-8000-000000000003",
      "tipo": "texto",
      "finalidade": "correcao",
      "texto": "O percentual de comissão é 2,5%.",
      "criado_em": "2025-11-28T14:05:00Z"
    }
  ],
  "versoes": [
    {
      "id": "00000000-0000-4000-8000-00000000000a",
      "versao": 1,
      "origem": "extracao",
      "representacao": {
        "nucleo": {
          "vigencia": {
            "inicio": "2025-11",
            "fim": "2025-11"
          },
          "loja": [
            "13"
          ],
          "marca": [
            "10",
            "20"
          ],
          "cargo": [
            "100",
            "300"
          ]
        },
        "especificacoes": []
      },
      "criada_em": "2025-11-28T14:03:00Z",
      "hash": "7545cef2c676b95728e3f3ee8308507cbd67d00b4075c6cf5acd892ecbc55434",
      "parametros": {
        "competencias": [
          "2025-11"
        ],
        "orcamento": 600000,
        "meta_venda": 28000000
      }
    },
    {
      "id": "00000000-0000-4000-8000-00000000000b",
      "versao": 2,
      "origem": "correcao",
      "representacao": {
        "nucleo": {
          "vigencia": {
            "inicio": "2025-11",
            "fim": "2025-11"
          },
          "loja": [
            "13"
          ],
          "marca": [
            "10",
            "20"
          ],
          "cargo": [
            "100",
            "300"
          ],
          "percentual": 0.025
        },
        "especificacoes": []
      },
      "criada_em": "2025-11-28T14:07:00Z",
      "hash": "1e7a6b003ca4b6123c3c13dd06f0c36dbdd01d6f7a9c81200d564237a50f3435",
      "parametros": {
        "competencias": [
          "2025-11"
        ],
        "orcamento": 600000,
        "meta_venda": 28000000
      },
      "regra_origem_id": "00000000-0000-4000-8000-00000000000a"
    }
  ],
  "etapas": [
    {
      "id": "00000000-0000-4000-8000-00000000001e",
      "no": "extracao_parametros",
      "concluido_em": "2025-11-28T14:03:00Z",
      "conclusao": {
        "resumo": "Regra extraída."
      },
      "regra_id": "00000000-0000-4000-8000-00000000000a",
      "submissao_id": "00000000-0000-4000-8000-000000000002",
      "prompt_id": "00000000-0000-4000-8000-000000000014"
    },
    {
      "id": "00000000-0000-4000-8000-00000000001f",
      "no": "validacao_dominio",
      "concluido_em": "2025-11-28T14:04:00Z",
      "conclusao": {
        "resumo": "Percentual ausente."
      },
      "regra_id": "00000000-0000-4000-8000-00000000000a"
    },
    {
      "id": "00000000-0000-4000-8000-000000000020",
      "no": "confirmacao",
      "concluido_em": "2025-11-28T14:05:00Z",
      "conclusao": {
        "resumo": "Correção recebida."
      },
      "regra_id": "00000000-0000-4000-8000-00000000000a"
    },
    {
      "id": "00000000-0000-4000-8000-000000000021",
      "no": "extracao_parametros",
      "concluido_em": "2025-11-28T14:07:00Z",
      "conclusao": {
        "resumo": "Percentual corrigido."
      },
      "regra_id": "00000000-0000-4000-8000-00000000000b",
      "submissao_id": "00000000-0000-4000-8000-000000000003",
      "prompt_id": "00000000-0000-4000-8000-000000000015"
    },
    {
      "id": "00000000-0000-4000-8000-000000000022",
      "no": "geracao_codigo",
      "concluido_em": "2025-11-28T14:09:00Z",
      "conclusao": {
        "resumo": "Código gerado.",
        "modo_geracao": "gerado"
      },
      "regra_id": "00000000-0000-4000-8000-00000000000b",
      "simulacao_id": "00000000-0000-4000-8000-00000000000d",
      "codigo_gerado_id": "00000000-0000-4000-8000-00000000000c",
      "prompt_id": "00000000-0000-4000-8000-000000000016"
    },
    {
      "id": "00000000-0000-4000-8000-000000000023",
      "no": "decisao",
      "concluido_em": "2025-11-28T14:12:00Z",
      "conclusao": {
        "resumo": "Resultado dentro do orçamento."
      },
      "regra_id": "00000000-0000-4000-8000-00000000000b",
      "resultado_id": "00000000-0000-4000-8000-00000000000e",
      "simulacao_id": "00000000-0000-4000-8000-00000000000d"
    },
    {
      "id": "00000000-0000-4000-8000-000000000024",
      "no": "decisao",
      "concluido_em": "2025-11-28T14:16:00Z",
      "conclusao": {
        "resumo": "Busca encerrada sem meta maior.",
        "desfecho_busca": "intervalo_esgotado",
        "candidatas_simuladas": 1
      },
      "regra_id": "00000000-0000-4000-8000-00000000000b"
    }
  ],
  "chamadas_modelo": [
    {
      "id": "00000000-0000-4000-8000-000000000014",
      "no": "extracao_parametros",
      "modelo": {
        "provedor": "openai",
        "modelo": "gpt-4.1",
        "versao": "2025-04-14",
        "parametros": {
          "temperature": 0,
          "top_p": 1,
          "seed": 42
        }
      },
      "prompt": "Comissão em novembro de 2025 na loja 13, marcas 10 e 20, cargos 100 e 300. Orçamento de 600 mil e meta de venda de 28 milhões.",
      "criado_em": "2025-11-28T14:01:00Z",
      "resposta": {
        "id": "00000000-0000-4000-8000-000000000046",
        "texto": "{\"nucleo\": {\"vigencia\": {\"inicio\": \"2025-11\", \"fim\": \"2025-11\"}, \"loja\": [\"13\"], \"marca\": [\"10\", \"20\"], \"cargo\": [\"100\", \"300\"]}, \"especificacoes\": []}",
        "consumo_tokens": {
          "tokens_in": 3120,
          "tokens_out": 480,
          "custo_usd": 0.0212
        },
        "criado_em": "2025-11-28T14:02:00Z"
      }
    },
    {
      "id": "00000000-0000-4000-8000-000000000015",
      "no": "extracao_parametros",
      "modelo": {
        "provedor": "openai",
        "modelo": "gpt-4.1",
        "versao": "2025-04-14",
        "parametros": {
          "temperature": 0,
          "top_p": 1,
          "seed": 42
        }
      },
      "prompt": "O percentual de comissão é 2,5%.",
      "criado_em": "2025-11-28T14:05:00Z",
      "resposta": {
        "id": "00000000-0000-4000-8000-000000000047",
        "texto": "{\"nucleo\": {\"vigencia\": {\"inicio\": \"2025-11\", \"fim\": \"2025-11\"}, \"loja\": [\"13\"], \"marca\": [\"10\", \"20\"], \"cargo\": [\"100\", \"300\"], \"percentual\": 0.025}, \"especificacoes\": []}",
        "consumo_tokens": {
          "tokens_in": 3120,
          "tokens_out": 480,
          "custo_usd": 0.0212
        },
        "criado_em": "2025-11-28T14:06:00Z"
      }
    },
    {
      "id": "00000000-0000-4000-8000-000000000016",
      "no": "geracao_codigo",
      "modelo": {
        "provedor": "openai",
        "modelo": "gpt-4.1",
        "versao": "2025-04-14",
        "parametros": {
          "temperature": 0,
          "top_p": 1,
          "seed": 42
        }
      },
      "prompt": "Gere o cálculo da regra corrigida.",
      "criado_em": "2025-11-28T14:07:00Z",
      "resposta": {
        "id": "00000000-0000-4000-8000-000000000048",
        "texto": "def aplicar_regra(bases, apuracao_base, competencias):\n    chaves = ['matricula', 'competencia']\n    vendas = bases['vendas'].groupby(chaves)['vlr_venda'].sum()\n    simulada = apuracao_base.copy()\n    venda = simulada.set_index(chaves).index.map(vendas).fillna(0)\n    alvo = (simulada.cod_loja == 13) & simulada.cod_marca.isin([10, 20]) & simulada.cod_cargo.isin([100, 300]) & simulada.competencia.isin(competencias)\n    simulada['comissao'] = simulada.comissao.where(~alvo, venda * 0.025)\n    efeitos = simulada[['matricula', 'competencia', 'cod_loja', 'cod_marca', 'cod_cargo']].copy()\n    efeitos['delta'] = simulada.comissao - apuracao_base.comissao\n    efeitos['elemento_ref'] = 'nucleo.percentual'\n    return {'apuracao_simulada': simulada, 'contribuicoes': efeitos[efeitos.delta != 0], 'elementos_implementados': ['nucleo.percentual']}\n",
        "consumo_tokens": {
          "tokens_in": 3120,
          "tokens_out": 480,
          "custo_usd": 0.0212
        },
        "criado_em": "2025-11-28T14:08:00Z"
      }
    }
  ],
  "codigos": [
    {
      "id": "00000000-0000-4000-8000-00000000000c",
      "regra_id": "00000000-0000-4000-8000-00000000000b",
      "linguagem": "python",
      "fonte": "def aplicar_regra(bases, apuracao_base, competencias):\n    chaves = ['matricula', 'competencia']\n    vendas = bases['vendas'].groupby(chaves)['vlr_venda'].sum()\n    simulada = apuracao_base.copy()\n    venda = simulada.set_index(chaves).index.map(vendas).fillna(0)\n    alvo = (simulada.cod_loja == 13) & simulada.cod_marca.isin([10, 20]) & simulada.cod_cargo.isin([100, 300]) & simulada.competencia.isin(competencias)\n    simulada['comissao'] = simulada.comissao.where(~alvo, venda * 0.025)\n    efeitos = simulada[['matricula', 'competencia', 'cod_loja', 'cod_marca', 'cod_cargo']].copy()\n    efeitos['delta'] = simulada.comissao - apuracao_base.comissao\n    efeitos['elemento_ref'] = 'nucleo.percentual'\n    return {'apuracao_simulada': simulada, 'contribuicoes': efeitos[efeitos.delta != 0], 'elementos_implementados': ['nucleo.percentual']}\n",
      "prompt_id": "00000000-0000-4000-8000-000000000016",
      "criado_em": "2025-11-28T14:09:00Z"
    }
  ],
  "resultados": [
    {
      "id": "00000000-0000-4000-8000-00000000000e",
      "codigo_gerado_id": "00000000-0000-4000-8000-00000000000c",
      "status": "sucesso",
      "proposito": "simulacao",
      "veredito": "viavel",
      "meta_venda": 28000000,
      "totais": {
        "baseline": 529520,
        "simulado": 541900,
        "diferenca_abs": 12380,
        "diferenca_pct": 0.0234,
        "orcamento": 600000,
        "vendas_historicas": 23583194.87
      },
      "assercoes": [
        {
          "nome": "sem_comissao_negativa",
          "resultado": "ok",
          "detalhe": null
        },
        {
          "nome": "sem_comissao_sem_venda",
          "resultado": "ok",
          "detalhe": null
        },
        {
          "nome": "soma_loja_igual_soma_matricula",
          "resultado": "ok",
          "detalhe": null
        }
      ],
      "decomposicao": {
        "elemento": {
          "nucleo.percentual": 12380
        },
        "loja": {
          "13": 12380
        },
        "marca": {
          "10": 12380
        },
        "cargo": {
          "100": 12380
        },
        "competencia": {
          "2025-11": 12380
        }
      },
      "criado_em": "2025-11-28T14:11:00Z"
    },
    {
      "id": "00000000-0000-4000-8000-00000000000f",
      "codigo_gerado_id": "00000000-0000-4000-8000-00000000000c",
      "status": "sucesso",
      "proposito": "busca_meta",
      "veredito": "inviavel",
      "meta_venda": 28500000,
      "totais": {
        "baseline": 529520,
        "simulado": 607500,
        "diferenca_abs": 77980,
        "diferenca_pct": 0.1473,
        "orcamento": 600000,
        "vendas_historicas": 23583194.87
      },
      "assercoes": [
        {
          "nome": "sem_comissao_negativa",
          "resultado": "ok",
          "detalhe": null
        },
        {
          "nome": "sem_comissao_sem_venda",
          "resultado": "ok",
          "detalhe": null
        },
        {
          "nome": "soma_loja_igual_soma_matricula",
          "resultado": "ok",
          "detalhe": null
        }
      ],
      "decomposicao": {
        "elemento": {
          "nucleo.percentual": 77980
        },
        "loja": {
          "13": 77980
        },
        "marca": {
          "10": 77980
        },
        "cargo": {
          "100": 77980
        },
        "competencia": {
          "2025-11": 77980
        }
      },
      "criado_em": "2025-11-28T14:15:00Z"
    }
  ],
  "simulacoes": [
    {
      "id": "00000000-0000-4000-8000-00000000000d",
      "regra_id": "00000000-0000-4000-8000-00000000000b",
      "codigo_gerado_id": "00000000-0000-4000-8000-00000000000c",
      "resultado_id": "00000000-0000-4000-8000-00000000000e",
      "flag_baixa_rastreabilidade": false,
      "criado_em": "2025-11-28T14:09:00Z"
    }
  ],
  "transicoes": [
    {
      "id": "00000000-0000-4000-8000-000000000050",
      "status_novo": "aguardando_transcricao",
      "ocorrido_em": "2025-11-28T14:00:00Z",
      "ator": "usuario"
    },
    {
      "id": "00000000-0000-4000-8000-000000000051",
      "status_novo": "gerando_regra",
      "ocorrido_em": "2025-11-28T14:01:00Z",
      "ator": "sistema",
      "status_anterior": "aguardando_transcricao"
    },
    {
      "id": "00000000-0000-4000-8000-000000000052",
      "status_novo": "aguardando_confirmacao_parametros",
      "ocorrido_em": "2025-11-28T14:04:00Z",
      "ator": "evento",
      "status_anterior": "gerando_regra"
    },
    {
      "id": "00000000-0000-4000-8000-000000000053",
      "status_novo": "gerando_regra",
      "ocorrido_em": "2025-11-28T14:07:00Z",
      "ator": "evento",
      "status_anterior": "aguardando_confirmacao_parametros"
    },
    {
      "id": "00000000-0000-4000-8000-000000000054",
      "status_novo": "simulando",
      "ocorrido_em": "2025-11-28T14:10:00Z",
      "ator": "evento",
      "status_anterior": "gerando_regra"
    },
    {
      "id": "00000000-0000-4000-8000-000000000055",
      "status_novo": "aguardando_decisao_usuario",
      "ocorrido_em": "2025-11-28T14:12:00Z",
      "ator": "evento",
      "status_anterior": "simulando"
    },
    {
      "id": "00000000-0000-4000-8000-000000000056",
      "status_novo": "liberado",
      "ocorrido_em": "2025-11-28T14:18:00Z",
      "ator": "usuario",
      "status_anterior": "aguardando_decisao_usuario"
    }
  ],
  "acoes": [
    {
      "id": "00000000-0000-4000-8000-000000000028",
      "acao": "salvar",
      "executado_em": "2025-11-28T14:18:00Z"
    }
  ],
  "rodadas": [
    {
      "id": "00000000-0000-4000-8000-000000000029",
      "rodada_anterior_id": null,
      "regra_analisada_id": "00000000-0000-4000-8000-00000000000a",
      "conflitos": [
        {
          "elementos": [
            "nucleo.percentual"
          ],
          "motivo": "percentual ausente"
        }
      ],
      "correcao": {
        "tipo": "texto",
        "texto": "O percentual de comissão é 2,5%.",
        "enviada_em": "2025-11-28T14:05:00Z"
      },
      "regra_resultante_id": "00000000-0000-4000-8000-00000000000b",
      "estado": "corrigida",
      "criada_em": "2025-11-28T14:04:00Z"
    }
  ],
  "sugestoes_meta": [
    {
      "regra_id": "00000000-0000-4000-8000-00000000000b",
      "motivo_sem_solucao": "intervalo_esgotado",
      "criada_em": "2025-11-28T14:16:00Z"
    }
  ],
  "explicacoes": [
    {
      "id": "00000000-0000-4000-8000-00000000002a",
      "resultado_id": "00000000-0000-4000-8000-00000000000e",
      "texto": "A comissão simulada de R$ 541.900 está dentro do orçamento de R$ 600.000.",
      "aderencia_conferida": true,
      "criado_em": "2025-11-28T14:17:00Z"
    }
  ]
} as unknown as RegistroAuditoria