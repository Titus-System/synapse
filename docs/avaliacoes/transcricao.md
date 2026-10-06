# Avaliação de provedores de transcrição — consolidado

- Data: 06/10/2026.
- Situação: revisão corrigida após contestação das anotações; conferência humana favorável e acerto quantitativo inconclusivo.
- Decisão para revisão: [ADR-007](../adrs/ADR-007.md).
- Corpus e áudio: [fixtures](../../api/src/test/resources/transcricao/README.md).

T-235 e T-230 ainda estão indisponíveis, conforme o usuário. Sua atualização é
encaminhamento futuro, não condição para apresentar estes resultados. A situação
de cada critério e o texto para a tarefa atual estão no [fechamento](fechamento-avaliacao.md).

## Resultado e recomendação

Deepgram Nova-3 e Groq whisper-large-v3 foram chamados nos mesmos 27 arquivos, uma vez por candidato/arquivo: 54 respostas HTTP 200. Os 22 Ogg iniciais possuem confirmação humana de correspondência ao texto esperado; dois MP4 e três WebM acrescentam evidência de formato, ruído, fala rápida e duração. OpenAI foi tentada duas vezes e retornou HTTP 429, com diagnóstico `credit_balance_exhausted` / `insufficient_quota`, sem transcrição.

**A reprovação por percentuais de acerto foi retirada.** O usuário esclareceu nesta conversa que as transcrições corresponderam ao que foi falado, além da confirmação anterior das gravações. Registrar essa avaliação humana favorável. As anotações textuais do assistente foram contestadas e não devem sustentar conclusão de erro do ASR, pontuação de qualidade ou descarte de candidatos.

O assistente não ouviu diretamente os áudios nesta sessão: a tentativa de fornecer um Ogg como entrada foi recusada pelo recurso com “audio content omitted because you do not support audio input”. A revisão anterior comparou textos e respostas ASR. Não apresentar esse procedimento como revisão auditiva independente.

O controle confirmado sem fala continua como observação separada: ambos produziram texto nele. Esse achado requer avaliação de tratamento ou aceite pelo responsável, mas não demonstra que todas as transcrições com fala falharam. Não há reprovação formal pela PO, vencedor aprovado ou alteração de fluxo.

## Provedor recomendado para aceite

**Deepgram Nova-3**, com `pt-BR`, endpoint europeu, `smart_format=false` e `mip_opt_out=true`, conforme [ADR-007](../adrs/ADR-007.md). A proposta considera a confirmação humana favorável, os três formatos efetivamente aceitos e os controles documentados de idioma, região e uso dos dados. A Groq permanece alternativa de menor latência observada. Não se afirma superioridade de precisão numérica, pois os percentuais anteriores foram retirados da conclusão.

Recomendação definida não é aprovação de produção. O responsável precisa ratificar o fornecedor e aceitar/tratar o resultado de texto no silêncio e as limitações listadas. T-235/T-230 indisponíveis não impedem apresentar essa proposta; encaminhamentos ficam prontos para registro posterior. Nenhum contrato ou fluxo foi alterado.

## Revisão de correspondência e acerto por tipo

O usuário entregou conferência dos 22 áudios iniciais e posteriormente confirmou que as transcrições também corresponderam à fala. É uma confirmação global; não houve nova anotação por ocorrência de cada candidato. Não converter essa declaração em 100% de precisão numérica nem manter as porcentagens contestadas.

| Tipo | Ocorrências por candidato no corpus inicial | Situação atual |
| --- | ---: | --- |
| Percentual | 8 | correspondência global confirmada pelo usuário; taxa específica não estabelecida |
| Monetário e limites | 20 | correspondência global confirmada pelo usuário; taxa específica não estabelecida |
| Data | 10 | correspondência global confirmada pelo usuário; taxa específica não estabelecida |
| Loja | 8 | correspondência global confirmada pelo usuário; taxa específica não estabelecida |
| Marca | 12 | correspondência global confirmada pelo usuário; taxa específica não estabelecida |
| Cargo | 6 | correspondência global confirmada pelo usuário; taxa específica não estabelecida |
| Matrícula | 8 | correspondência global confirmada pelo usuário; taxa específica não estabelecida |
| Exclusão | 6 | correspondência global confirmada pelo usuário; taxa específica não estabelecida |

As contagens de 78 ocorrências por candidato vêm do corpus e são preservadas. As 156 anotações anteriores e a agregação permanecem somente para auditoria, com status contestado. Não são a conclusão vigente. Há diferenças entre respostas e referências escritas em alguns arquivos; sem escuta direta e referência resolvida, a origem dessas diferenças permanece inconclusiva. Não remapear arquivos, alterar números nas respostas ou alegar ouvir a fala com base na concordância de provedores.

## Latência e comparação lexical histórica

| Medida no corpus inicial de 22 Ogg | Deepgram | Groq |
| --- | ---: | ---: |
| HTTP 200 | 22/22 | 22/22 |
| Média | 1.030,41 ms | 582,18 ms |
| Mediana nearest rank | 619 ms | 447 ms |
| p95 nearest rank | 3.302 ms | 1.160 ms |
| Comparação lexical histórica com referências anteriores | arquivada; não usar como qualidade auditiva | arquivada; não usar como qualidade auditiva |

O cálculo lexical anterior usa referências escritas e penaliza números em algarismos diante de palavras. Com a correspondência auditiva contestada, ele permanece histórico e não estabelece qualidade ou origem de erros. Rodadas em horários diferentes, não intercaladas; uma tentativa por arquivo, sem variabilidade de repetição.

| Complemento | Deepgram | Groq |
| --- | ---: | ---: |
| MP4/ruído, 7,40 s | 3.930 ms | 478 ms |
| MP4/fala rápida, 6,44 s | 925 ms | 628 ms |
| WebM/controle sem fala, 6,78 s | 1.492 ms | 345 ms |
| WebM/conteúdo pendente, 30,54 s | 1.853 ms | 1.212 ms |
| WebM/leitura longa, 113,16 s | 6.216 ms | 2.337 ms |

No controle confirmado sem fala, Deepgram respondeu `o código é código de` e Groq respondeu `E aí`: **1/1 controle com texto inventado em cada candidato**. Não extrapolar a frequência desse caso para produção. A T-232 rejeita texto vazio, mas não impede esse texto inventado não vazio.

Os dois MP4 preservam textualmente os quatro elementos de r01 em cada resposta; suas leituras não tiveram a mesma exportação de conferência do corpus inicial. Os WebM de 30,54 e 113,16 segundos não possuem sequência/transcrição esperada confirmada e não entram na tabela por tipo. O usuário determinou manter o longo de 113 segundos. Não se exige áudio de exatamente três minutos, mas a latência no limite de 180 segundos ficou não avaliada. A faixa 165–180 era proposta de protocolo, não critério explícito da tarefa.

## Integração, formatos, limites e custos

| Critério | Deepgram Nova-3 | Groq whisper-large-v3 |
| --- | --- | --- |
| REST/Java | POST /v1/listen, bytes no corpo | POST /openai/v1/audio/transcriptions, multipart |
| Autorização | Token DEEPGRAM_API_KEY | Bearer GROQ_API_KEY |
| Idioma enviado | pt-BR | pt, ISO 639-1; variante brasileira avaliada nos áudios, sem seletor pt-BR |
| Formatos efetivamente aceitos | Ogg/Opus, MP4/Opus, WebM/Opus | Ogg/Opus, MP4/Opus, WebM/Opus |
| WAV | não testado | não testado |
| Limite documental de tamanho | até 2 GB; limite do produto continua 5 MB | 25 MB no plano gratuito; produto continua 5 MB |
| Duração independente | não confirmada; timeout do serviço não equivale a duração máxima | não confirmada; limite de bytes não define duração |
| Tarifa nominal documental | US$ 0,0043/min, Nova-3 monolíngue pré-gravado | US$ 0,111/hora, mínimo de 10 s por chamada |
| Oferta gratuita | US$ 200 iniciais, elegibilidade/saldo dependem da conta | cota gratuita com limites de requisições e segundos de áudio |
| Exemplo nominal de 3 min | US$ 0,0129 | US$ 0,00555 antes de créditos/cotas |
| Estimativa nominal dos 27 envios | US$ 0,02669 | US$ 0,01263, mínimo de 10 s incluído |
| Resposta consumida | results.channels[0].alternatives[0].transcript | text em JSON |

Estimativa calculada sobre 372,43938 segundos de áudio por candidato; Groq sobre 409,699396 segundos com mínimo de dez segundos por chamada. Não é fatura nem promessa de custo: verificar plano, arredondamentos, condições de opt-out, créditos e uso real no painel. Nenhuma compra de créditos ou plano foi realizada.

Fontes verificadas em 06/10/2026: [Deepgram preços](https://deepgram.com/pricing), [formatos](https://developers.deepgram.com/docs/supported-audio-formats), [pré-gravado](https://developers.deepgram.com/docs/pre-recorded-audio), [Groq transcrição](https://console.groq.com/docs/speech-to-text), [Groq cotas](https://console.groq.com/docs/rate-limits). A publicação de suporte não comprova todos os codecs; aqui foram testados os arquivos recebidos sem conversão.

## Dados e alternativas

Deepgram: endpoint europeu com `mip_opt_out=true` e `smart_format=false`. A [política](https://developers.deepgram.com/trust-security/your-data) informa que opt-out exclui melhoria de modelos e retenção do conteúdo após resposta; metadados de uso permanecem por 90 dias e resumos por mais tempo. Endpoint regional mais opt-out define o processamento na UE. Flag enviada pelo script, sem conferência independente do log do painel.

Groq: segundo a [política](https://console.groq.com/docs/your-data), conteúdo de inferência não é retido por padrão, salvo exceções de confiabilidade/abuso, até 30 dias ou obrigações legais. ZDR pode ser habilitado. Não conferimos a configuração ZDR da conta. Dados retidos ficam em GCP nos EUA; isso não determina por si só a região de processamento. Uso para treino e obrigações contratuais precisam ser confirmados explicitamente, não deduzidos de ausência de retenção. A PO precisa avaliar região, transferência internacional, retenção local, transparência e documentação aplicável antes de produção.

Autorização de ambas as vozes para repositório e envio à Deepgram, OpenAI e Groq foi confirmada pelo usuário nesta conversa. Pseudônimos no conjunto versionável; original da revisão humana mantido no workspace. Comprovantes externos não conferidos. Não há autorização jurídica ou aceite da PO presumidos.

OpenAI é alternativa sem resultados de qualidade devido ao crédito esgotado. O codegen usa Google Gemini; reaproveitar fornecedor/chave foi considerado, mas não qualificado como ASR dedicado nesta rodada. Não usar a LLM geral como substituto automático nem alegar descarte por qualidade de um modelo não testado. Cliente Java e conversão de áudio/números estão fora do escopo.

## Reprodução e verificação

Evidências preservadas: [Ogg Deepgram](piloto-20261006-132246.json), [Ogg Groq](piloto-groq-20261006-135904.json), [MP4](complementos-mp4-20261006-141623.json), [WebM](complementos-webm-20261006-142207.json), [anotações e métricas](metricas-consolidadas.json), [diagnóstico OpenAI](diagnostico-openai.json).

Comandos executados nesta avaliação: scripts auxiliares `../work/piloto-transcricao.ps1`, `../work/piloto-groq.ps1`, `../work/coletar-complementos.ps1`, `../work/coletar-webm.ps1`, na raiz do repo, com credenciais de ambiente não exibidas. Helpers do coletor versionado usados para envio, leitura mínima, HTTP e tempo; Groq/OAI multipart usam o modelo declarado pelo candidato. Repetição da coleta implica envio externo e possível cobrança. Os auxiliares são específicos ao workspace; as entradas/respostas/hashes e as opções permitem auditar esta rodada. As chamadas originais não dependem de nova chamada para verificar documentos.

Agregação histórica sem API: `python docs/avaliacoes/consolidar-metricas.py --historico`. A saída mantém status contestado; não é a revisão vigente. Verifica 22 entradas por candidato e 78 ocorrências, sem esconder os arquivos suspeitos. Valores anotados são dados de revisão, não regras de extração ou conversão. O avaliador completo `-Mode resultados` permanece reservado ao protocolo completo; não contornamos seu bloqueio para aprovar esta matriz parcial.

Verificações offline: `avaliar-transcricao.ps1 -Mode corpus`, `-Mode autoteste` (9 casos), `test-avaliar-transcricao.ps1` (11 cenários), `-Mode gravacoes`, multipart com modelos OpenAI/Groq sem rede, `git diff --check`; resultados aprovados ou conjunto incompleto explicitamente diagnosticado. Sintaxe JavaScript e 22 caminhos da página de revisão conferidos. Gate Java não aprovado nesta sessão; ambiente anterior possuía JDK 17.

E1: tentativa documentada em [verificacao-e1.md](verificacao-e1.md), bloqueada por Windows Application Control ao carregar `_uuid_utils`, antes dos casos. Nenhum teste E1 aprovado. A documentação atual do codegen atribui conferência determinística numérica à T-210. A representação por extenso/algarismos continua uma observação de ASR, não prova do comportamento da extração.

## Pendências para aceite

1. Resolver por conferência auditiva humana as diferenças entre referência escrita e respostas, se exigido pelo decisor; anotações anteriores contestadas não são prova de erro.
2. Decisão do responsável sobre o achado de texto no silêncio e aceite das limitações; não pressupor reprovação das transcrições com fala.
3. WAV, controles sem fala nos formatos restantes, navegador/versão e sequência esperada dos dois WebM com fala ainda não confirmados. Cota/condições da conta e política de dados revisadas.
4. E1 em ambiente autorizado e, se exigido pelo decisor, repetições intercaladas. Limite de 180 s não testado.
5. ADR aceito por quem decide; registrar resultado na T-235/T-230. Não houve envio de comentários a issues, commit, PR ou aprovação do responsável.

Material consolidado para revisão, **não tarefa encerrada nem provedor liberado para produção**.
