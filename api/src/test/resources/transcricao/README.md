# Fixtures de avaliação de transcrição

Este diretório prepara a decisão do [ADR-007](../../../../../docs/adrs/ADR-007.md)
e será reaproveitado pela T-235. Foram recebidos 24 arquivos Ogg/Opus; **22 estão
incluídos na comparação**, correspondentes a 11 frases em cada grupo de voz.
A frase 9 está excluída nas duas vozes por instrução do usuário, registrada em
`excluded_phrase_ids` no manifesto. Seus arquivos permanecem preservados.
Há resultados reais de Deepgram e Groq para os 22 Ogg, dois MP4 e três WebM,
com métricas consolidadas e limitações no relatório. O usuário confirmou em 06/10/2026 que as
duas pessoas autorizaram o uso no repositório e o envio aos provedores em
avaliação, incluindo envio à Groq. O manifesto referencia essa declaração; os comprovantes originais
ainda precisam ser conferidos pelo responsável.

`gravacoes.json` contém caminhos, SHA-256, tamanho, codec e duração aproximada dos
arquivos recebidos. O aplicativo informado foi WhatsApp, sem versão: a `voz-a`
foi gravada em ambiente silencioso e a `voz-b` em ambiente barulhento, classificado
como `office_noise` com a origem do ruído ainda pendente de confirmação.
`reading_verified=false` significa que o texto esperado vem do corpus e
a leitura real ainda precisa ser conferida; não é uma transcrição obtida do áudio.

As 22 leituras Ogg foram conferidas pelo usuário em arquivo exportado; o
controle WebM de 6,78 segundos foi confirmado sem fala. Duas leituras MP4
continuam sem conferência exportada. WebM de 30,54/113,16 segundos ficam em
`complementos-pendentes.json` enquanto conteúdo e referência são confirmados.
O arquivo longo foi aceito pelo usuário para evidência parcial; teste no limite
de 180 segundos não foi executado. O conjunto completo não está aprovado.

`corpus.json` contém 12 frases e 44 elementos críticos. `text` é a leitura
esperada, `spoken` é o trecho que deve ser preservado e `value` é a referência
semântica para revisão humana. Esses valores não são saída do ASR, parâmetros de
simulação nem uma implementação de conversão de números por extenso.

As adaptações vêm dos tipos de regra de `dataset_domrock/Especificacao.md`, com
frases coloquiais adicionais. Os identificadores `MATRIC-900001` a `MATRIC-900004`
são fictícios, seguem o exemplo canônico `MATRIC-<número>` e não foram encontrados
nas bases textuais pesquisadas. A loja `07` testa preservação de zero inicial;
sua existência no domínio não é requisito do ASR. Não copie nomes, matrículas ou
outras informações de pessoas reais para este conjunto.

## Captura e autorização

1. Obtenha autorização de pelo menos duas pessoas para versionar sua voz e
   submetê-la aos provedores candidatos. Identifique cada uma por pseudônimo
   (`voz-a`, `voz-b`). A voz continua sendo dado pessoal mesmo com texto fictício.
2. Guarde o comprovante de consentimento no local definido pelo responsável.
   Versione somente sua referência, data, quem autorizou e o alcance concedido.
   Não preencha o manifesto com consentimentos fictícios.
3. Grave cada frase incluída na comparação nas duas vozes. O recorte atual tem
   11 frases, com a frase 9 excluída. Distribua entre elas os quatro
   formatos da T-230 (`webm`, `ogg`, `wav`, `mp4`), usando capturas reais do
   navegador e registrando codec, navegador e versão. Não renomeie extensões nem
   converta arquivos para simular suporte nativo. Se um formato não puder ser
   capturado, registre a pendência no relatório.
4. Inclua fala com ruído de escritório e fala rápida. Ruído não pode conter
   conversas de terceiros. Ouça cada arquivo e confira a leitura esperada; se a
   pessoa trocar um número ou omitir uma condição, regrave.
5. Grave oito controles sem fala: um em ambiente silencioso e um com ruído de
   escritório para cada formato. Texto esperado: string vazia. Inclua pelo menos
   uma leitura longa de 165 a 180 segundos, concatenando frases do corpus, para
   medir a latência próxima ao limite do produto.
6. Salve em `audio/`. Cada arquivo deve ter até 5.000.000 bytes e 180 segundos;
   o conjunto tem orçamento de 20 MB. Registre duração medida ou conferida no
   navegador. O avaliador verifica metadados e hashes, mas não decodifica áudio
   para confirmar contêiner, codec, duração ou identidade da voz.

Preencha `gravacoes.json` com esta estrutura (os valores abaixo são **exemplos de
estrutura**, não gravações entregues):

```json
{
  "version": 1,
  "speakers": [
    {
      "id": "voz-a",
      "authorized_by": "pseudônimo de quem concedeu a autorização",
      "authorized_on": "2026-10-05",
      "consent_reference": "referência do comprovante mantido pelo responsável",
      "repository_authorized": true,
      "external_processing_authorized": true
    }
  ],
  "recordings": [
    {
      "id": "voz-a-r01-webm",
      "speaker_id": "voz-a",
      "file": "audio/voz-a-r01.webm",
      "sha256": "substituir pelo SHA-256 real",
      "format": "webm",
      "codec": "opus",
      "duration_seconds": 12.4,
      "browser": "nome e versão reais",
      "condition": "office_noise",
      "kind": "speech",
      "phrase_ids": ["r01"],
      "expected_text": "Na loja treze, a comissão da marca dez para o cargo cem será de dois vírgula cinco por cento."
    }
  ]
}
```

`condition`: `quiet`, `office_noise` ou `fast`. `kind`: `speech`, `silence` ou
`long`. Para silêncio, `phrase_ids` é `[]` e `expected_text` é `""`. Para leitura
longa, informe a sequência de frases, inclusive repetições; `expected_text` deve
ser exatamente a concatenação de seus textos separados por espaço. A posição de
cada frase identifica a ocorrência dos elementos, começando em zero:
`0:r01.percentual`, `1:r02.marca`, etc.

`excluded_phrase_ids` registra exclusões explícitas do conjunto. O avaliador
desconsidera uma gravação que contenha uma dessas frases, exige ao menos dez
frases ativas e utiliza o mesmo recorte para todos os candidatos. A exclusão da
frase 9 não dispensa os demais formatos, controles ou autorizações.

```powershell
Get-FileHash -Algorithm SHA256 api/src/test/resources/transcricao/audio/voz-a-r01.webm
& ./api/scripts/avaliar-transcricao.ps1 -Mode corpus
& ./api/scripts/avaliar-transcricao.ps1 -Mode gravacoes
```

O coletor final aceita `-SecondProvider groq` para comparar Deepgram e Groq,
sem exigir OpenAI. O padrão `openai` foi preservado. `-Mode planejar` não envia
áudio; `-Mode coletar` mantém o gate de cobertura, conferência e credenciais.
A estimativa nominal do coletor considera o mínimo faturável Groq
de dez segundos por chamada, assim como a estimativa consolidada do relatório.
Não usar o planejamento para afirmar custo faturado ou aceitação da rodada.

O modo `gravacoes` verifica os arquivos e os metadados disponíveis e lista todas
as pendências de cobertura. Um conjunto parcial retorna
`status=gravacoes_incompletas`, `ready_for_comparison=false` e
`missing_requirements`; isso não aceita a avaliação nem chama provedores.
Dados inválidos, arquivos ausentes, hashes divergentes e autorização ausente
continuam sendo erros. O modo `resultados` exige a cobertura completa antes de
agregar respostas reais. A conferência humana das leituras, das autorizações e
da captura no navegador também continua necessária.

## Execução e revisão das respostas

O [relatório](../../../../../docs/avaliacoes/transcricao.md) define os candidatos,
as opções das requisições e a política de dados. Configure as chaves no ambiente
do processo. Não grave chaves, cabeçalhos de autorização, dumps de ambiente ou
comandos com segredos expandidos em arquivos. O script de avaliação é **offline**
e não implementa o cliente Java da T-235 nem chama provedores.

Envie cada arquivo, sem conversão, três vezes a cada candidato. Intercale a ordem
dos provedores e registre também timeout, erro e formato recusado. Meça do início
do envio até a resposta completa com relógio monotônico, incluindo upload e
falhas. Registre data da execução, modelo/versão, região/endpoint, opções,
identificador de requisição quando disponível, HTTP e duração. Arquive somente
corpos de respostas sanitizados e sem credenciais junto ao relatório da rodada.
Um alias pode mudar: uma execução futura não substitui a evidência desta rodada.

Revise a transcrição contra a gravação. Para cada ocorrência de elemento,
marque `correct` somente se valor, unidade, alvo, limite de faixa e sentido da
condição foram preservados. Um percentual associado ao cargo errado é erro;
perder uma exclusão é erro. Algarismos e palavras equivalentes contam como
acerto semântico, mas registre a representação separadamente (`digits`, `words`,
`mixed`, `absent`). `evidence` contém o trecho literal da resposta. Conte também
elementos críticos inventados em `unexpected_elements`. Essa revisão é humana;
o script não tenta interpretar transcrição com regex nem com LLM.

O arquivo de resultados tem este formato. Complete a matriz inteira para gerar
métricas; este exemplo isolado não passa no modo `resultados`:

```json
{
  "version": 1,
  "candidates": [
    {
      "id": "deepgram-nova3",
      "provider": "deepgram",
      "model": "nova-3",
      "endpoint": "https://api.eu.deepgram.com/v1/listen",
      "language": "pt-BR",
      "settings": {"language": "pt-BR", "smart_format": false, "mip_opt_out": true},
      "usd_per_minute": 0.0043
    }
  ],
  "runs": [
    {
      "candidate_id": "deepgram-nova3",
      "recording_id": "voz-a-r01-webm",
      "attempt": 1,
      "audio_sha256": "substituir pelo SHA-256 real",
      "status": "ok",
      "http_status": 200,
      "latency_ms": 800,
      "text": "substituir pela resposta real",
      "reviewed_by": "pseudônimo do revisor",
      "unexpected_elements": 0,
      "annotations": [
        {"element_id": "0:r01.percentual", "correct": false, "representation": "absent", "evidence": ""}
      ]
    }
  ]
}
```

Inclua as anotações de **todos** os elementos em respostas `ok`, inclusive quando
o texto for vazio. Para `error`/`unsupported`, use texto vazio, anotações vazias e
o HTTP observado; zero identifica falha sem resposta HTTP, como timeout. Esses
casos contam como erro de todos os elementos esperados. Uma resposta 2xx com JSON
inválido é `error`, com o HTTP real preservado. Registre a causa sanitizada na
evidência da rodada; não invente outro status HTTP para agregá-la.

```powershell
& ./api/scripts/avaliar-transcricao.ps1 -Mode autoteste
& ./api/scripts/test-avaliar-transcricao.ps1
& ./api/scripts/avaliar-transcricao.ps1 -Mode resultados -ResultsPath docs/avaliacoes/rodada-transcricao.json
```

O script calcula acerto por tipo, WER micro, latências de todas as tentativas
(mediana por nearest rank e p95), p95 dos áudios longos, sucesso por formato,
silêncio com texto, representações e custo nominal para todas as tentativas.
Não remove falhas do denominador nem gera resultado para matriz incompleta.
WER tokeniza palavras/números, ignora caixa e pontuação, preserva acentos e **não
converte** números; portanto, escrever `2,5%` pode elevar WER mesmo preservando o
valor. WER não é definido para silêncio: avalie texto inventado separadamente.
O custo é uma estimativa conservadora de minutos enviados, não a fatura; confira
arredondamentos, créditos, cobrança de falhas e uso real no painel do provedor.

Publique também no relatório os cortes por voz, condição e representação; a
agregação principal não demonstra sozinha que ruído ou fala rápida funcionaram.
Uma segunda pessoa deve conferir os erros críticos e as evidências antes de
aceitar o ADR. As fixtures de voz somente estarão entregues depois de os arquivos
reais, o manifesto completo e as autorizações serem revisados.
