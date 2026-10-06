> HISTÓRICO CONTESTADO: as anotações deste documento foram contestadas pelo usuário. Consulte transcricao.md para a conclusão corrigida; não usar este texto como reprovação vigente.
# Comparação preliminar Deepgram × Groq — 06/10/2026

Mesmos 22 arquivos Ogg/Opus, hashes conferidos, uma tentativa por arquivo por candidato, sem conversão. Deepgram Nova-3 no endpoint europeu e Groq whisper-large-v3 no endpoint padrão. Rodadas em horários diferentes, não intercaladas; por isso a diferença de latência também pode refletir rede e carga. Autorização de envio à Groq confirmada diretamente pelo usuário e registrada no manifesto. Leituras não conferidas auditivamente, cobertura incompleta: esta rodada não satisfaz a avaliação final.

Evidências: [Deepgram](piloto-20261006-132246.json), [Groq](piloto-groq-20261006-135904.json). Reprodução auxiliar Groq: `& ./docs/avaliacoes/reproduzir-piloto-groq.ps1`. O script é específico ao workspace desta rodada, realiza chamadas externas, pausa quatro segundos entre arquivos e interrompe em HTTP 401/403/429. Reutiliza os helpers do coletor; não exige nem afirma conjunto completo. A avaliação final continua usando o procedimento do README com três tentativas e cobertura completa. Não repetir chamadas por necessidade de revalidar documentos.

| Medida observada | Deepgram | Groq |
| --- | --- | --- |
| Sucesso HTTP | 22/22 | 22/22 |
| Média | 1.030,41 ms | 582,18 ms |
| Mediana nearest rank | 619 ms | 447 ms |
| p95 nearest rank | 3.302 ms | 1.160 ms |
| Formato efetivamente testado | Ogg/Opus | Ogg/Opus |
| Latência para três minutos | não testada | não testada |
| Qualidade final por tipo | pendente | pendente |

Latência inclui upload e leitura da resposta. Não inclui a pausa de quatro segundos entre chamadas Groq. Amostra pequena de áudios curtos não define timeout da T-235. Preço de tabela e crédito gratuito não são custo faturado observado.

## Achados textuais

Ambos retornaram conteúdo semelhante entre si, diferente da referência, para voz-a-r04 até voz-a-r08. Isso reforça a hipótese de associação incorreta de arquivos, mas não comprova a fala original. Preservar manifesto e não calcular acerto sobre referências suspeitas como se estivessem validadas.

Groq preservou a matrícula de r03 em `900001` nas duas vozes, onde Deepgram produziu sequências divergentes. Entretanto, em voz-a-r11 Groq retornou `90003` e `90004` no lugar das referências `900003` e `900004`. Em voz-b-r11 os números aparecem conforme a referência, com prefixo reconhecido como `matrique`. Esses achados precisam de conferência no áudio e no E1: comparação com texto esperado não atribui automaticamente a origem do erro ao provedor.

Em voz-b-r01 e voz-b-r06, Groq retornou `cargo`, enquanto Deepgram retornou `carro`. Groq usa com frequência algarismos (`2,5%`, `R$ 1.250,50`), Deepgram frequentemente preserva números por extenso com smart_format=false. Não converter saídas para favorecer um candidato. Verificar o comportamento real do E1 antes de decidir.

## Integração e política Groq

`POST https://api.groq.com/openai/v1/audio/transcriptions`, Bearer, multipart `file`, `model=whisper-large-v3`, `language=pt`, `response_format=json`; temperatura padrão zero, sem prompt contendo frase esperada. Consumo mínimo: campo JSON `text`. Idioma `pt` não é seletor específico de variante pt-BR.

A [documentação de transcrição](https://console.groq.com/docs/speech-to-text) lista WebM, Ogg, WAV e MP4 e limite de arquivo de 25 MB no plano gratuito; somente Ogg foi verificado aqui. Tarifa documental whisper-large-v3: US$ 0,111/hora, com mínimo faturável de dez segundos por chamada; a gratuidade depende da [cota da conta](https://console.groq.com/docs/rate-limits). Limite efetivo de duração e região de processamento precisam ser confirmados, sem inferir duração a partir do limite de bytes.

A [política de dados](https://console.groq.com/docs/your-data) informa ausência de retenção de conteúdo por padrão em inferência, com exceções para confiabilidade e abuso de até 30 dias, salvo exigências legais. ZDR pode ser habilitado nos controles de dados. Dados retidos ficam em GCP nos EUA; isso não comprova a região de processamento da chamada. Configuração ZDR desta conta não conferida; uso para treino, condições contratuais e requisitos da PO ainda precisam de revisão explícita.

## Decisão e pendências

Não aceitar vencedor com esta rodada. Ambos apresentam divergências críticas frente ao texto esperado; há também problema provável de fixtures. Corrigir/conferir as referências por escuta, completar formatos, condições, silêncio e áudio longo, revisar por elemento e testar E1. Se nenhum atender, levar à PO a decisão sobre revisão humana da transcrição. OpenAI permanece alternativa não avaliada em qualidade por crédito esgotado.

Nenhuma compra, alteração de contrato da T-230 ou implementação de cliente Java foi feita. O helper multipart foi ajustado para usar o modelo do candidato; requisições OpenAI e Groq verificadas offline com chave fictícia. Nove autotestes e onze testes de agregação passaram. Gate Java, extração E1 e ZDR não verificados.
