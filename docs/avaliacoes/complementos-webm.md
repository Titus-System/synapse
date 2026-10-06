# Complementos WebM — 06/10/2026

[Rodada real](complementos-webm-20261006-142207.json): mesmos três WebM/Opus enviados sem conversão a Deepgram Nova-3 e Groq whisper-large-v3, uma tentativa por arquivo/candidato. Seis HTTP 200. SHA-256 conferido. Fontes e metadados medidos preservados em `api/src/test/resources/transcricao/complementos-pendentes.json`; arquivos copiados para as fixtures, sem inclusão automática na matriz aceita.

| Arquivo (sufixo) | Duração do contêiner | Deepgram | Groq |
| --- | --- | --- | --- |
| 6271306.webm | 6,78 s | 1.492 ms | 345 ms |
| 6307437.webm | 30,54 s | 1.853 ms | 1.212 ms |
| long-quiet-1791296431491.webm | 113,16 s | 6.216 ms | 2.337 ms |

Duração calculada por Duration × TimecodeScale no WebM. Rótulos de captura no nome não comprovam conteúdo ou condição. O áudio longo está abaixo da faixa de 165–180 segundos do protocolo local: não passa automaticamente a ser controle próximo ao limite.

Arquivo de 6,78 segundos: Deepgram respondeu `o código é código de`; Groq respondeu `E aí`. Se o usuário confirmar gravação sem fala, registrar ambos como texto inventado em silêncio. Essa classificação permanece pendente; não afirmar alucinação sem conhecer o áudio original.

Arquivo de 30,54 segundos: ambos produziram trecho de intervalo de novembro, admissão/cargo/bônus e começo de regra de comissão. Não atribuir automaticamente à frase r01 pelo nome do arquivo nem afirmar silêncio. Confirmar fala efetivamente gravada e referências.

Arquivo longo: ambos produziram uma sequência semelhante ao roteiro, com diferenças frente ao corpus, incluindo matrículas, vendas semanais em vez de mensais e limite de 125 mil em vez de 120 mil. Ambos também transcreveram a instrução final da página (`Repita a sequência...`). Confirmar sequência lida, repetições, correções e valores no áudio antes de gerar expected_text. Não usar texto de ASR como ground truth nem corrigir automaticamente a fala.

Comando auxiliar executado: `& ../work/coletar-webm.ps1`, na raiz do repositório. Sem prompt da frase esperada; tempo inclui upload e resposta, sem pausas entre chamadas. Uma tentativa, não a matriz final de três tentativas. Nenhum segredo registrado. Validador de fixtures e git diff --check executados após preservar os complementos como pendentes. E1 segue bloqueado e o ADR segue proposto.

## Confirmação posterior do usuário

O usuário confirmou que o arquivo 6271306.webm foi gravado sem fala. Foi incorporado como controle WebM/quiet, expected_text vazio. Ambos os candidatos produziram texto não vazio nessa única tentativa: ocorrência de texto inventado em silêncio em ambos. Não estimar taxa populacional a partir desse caso.

O usuário escolheu manter o áudio de 113,16 segundos. A tarefa pede considerar latência para gravações de até três minutos; não determina que um arquivo tenha exatamente três minutos. A faixa 165–180 segundos era proposta do protocolo auxiliar, não requisito textual da tarefa. Este áudio permite medir latência em 113 segundos, sem comprovar o comportamento no limite de 180 segundos. Essa limitação será registrada, sem exigir nova gravação nesta etapa.
