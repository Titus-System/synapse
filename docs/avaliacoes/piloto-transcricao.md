# Rodada preliminar de transcrição — 06/10/2026

Evidência: [respostas reais](piloto-20261006-132246.json). Autorização para versionamento e envio aos dois provedores confirmada diretamente pelo usuário nesta conversa em 06/10/2026 e registrada no manifesto.

Executado: `& ../work/piloto-transcricao.ps1`, a partir do diretório do chat. Script auxiliar local reutilizou `Invoke-TranscriptionAttempt` do coletor, com uma tentativa por arquivo, timeout de 60 segundos, conferência de SHA-256 e sem conversão de áudio. A rodada foi explicitamente separada da avaliação final: leituras não conferidas e cobertura incompleta. O script auxiliar permanece no diretório de trabalho do chat; o JSON registra respostas, endpoints, modelos, horário, HTTP e latência. Para a rodada final reproduzível, usar o coletor versionado após completar as fixtures.

- Deepgram Nova-3: 22 arquivos Ogg/Opus enviados ao endpoint europeu; 22 respostas HTTP 200 com texto extraído.
- OpenAI gpt-4o-transcribe: primeira tentativa retornou HTTP 429; chamadas seguintes a esse candidato interrompidas.
- HTTP 429 não determina sozinho se houve falta de saldo, quota ou limite de requisições. Conferir o painel da conta antes de repetir. Corpo de erro e credenciais não foram armazenados.
- Opções: Deepgram `language=pt-BR`, `smart_format=false`, `mip_opt_out=true`; OpenAI `language=pt`, `response_format=json`.

Sucesso HTTP não mede acerto dos números. Anotações por elemento, revisão contra áudio, WER, testes com E1, controles de silêncio, demais formatos, fala rápida e áudio longo permanecem pendentes. Não há comparação completa entre dois provedores, decisão aceita ou custo faturado confirmado. Não usar esta rodada para declarar a tarefa concluída.
