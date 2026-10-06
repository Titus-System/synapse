# Encaminhamentos para submissão — 06/10/2026

## Tarefa atual

> Entregues relatório de avaliação, fixtures, respostas reais, comandos de reprodução e ADR-007 proposto. Deepgram Nova-3 recomendada com pt-BR, endpoint europeu, smart_format=false e mip_opt_out=true. Comparação com Groq whisper-large-v3 nos mesmos 27 arquivos: 54 HTTP 200. Correspondência das transcrições confirmada pelo usuário; percentuais assistidos anteriores contestados e retirados da conclusão. A recomendação é operacional, sem alegação de superioridade de precisão. Ambos produziram texto no controle confirmado sem fala. Solicita-se aceite do decisor para a escolha e as limitações explícitas: métricas por tipo inconclusivas, WAV/controles incompletos, E1 bloqueado, duração medida até 113 segundos. T-235/T-230 indisponíveis; encaminhamentos preservados para registro posterior.

## T-235 — quando disponível

Fornecedor recomendado: Deepgram Nova-3. Endpoint https://api.eu.deepgram.com/v1/listen; áudio binário; model=nova-3, language=pt-BR, smart_format=false, mip_opt_out=true. Credencial DEEPGRAM_API_KEY no ambiente. Resposta: results.channels[0].alternatives[0].transcript. Seguir configuração por application.yaml/app, AppProperties e placeholders de .env.example. Timeout deve ser ratificado, não extrapolado de 113 segundos. Fixtures em api/src/test/resources/transcricao e relatório em docs/avaliacoes/transcricao.md. Aceite dos riscos e decisão do responsável pendentes; não implementar mudança de escopo por esta mensagem.

## T-230 — quando disponível

Ogg/Opus, WebM/Opus e MP4/Opus foram aceitos na rodada por Deepgram e Groq. WAV consta de suporte documental, mas não foi testado. Manter o contrato atual; eventual redução precisa de autorização e validação. Captura até três minutos continua especificação; limite de 180 segundos não foi medido nesta avaliação.

## Aceite solicitado

O decisor deve ratificar a Deepgram recomendada e aceitar/tratar o texto produzido sem fala. A PO decide eventual revisão obrigatória ou outra mudança de escopo. Limitações de cobertura/quantificação são apresentadas para aceite ou complementação, sem inventar métricas. Não marcar tarefa encerrada nem ADR aceito antes desse ato. Nenhuma postagem externa, commit, PR ou contratação foi feita.
