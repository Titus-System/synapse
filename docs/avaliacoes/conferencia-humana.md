> HISTÓRICO CONTESTADO: as anotações deste documento foram contestadas pelo usuário. Consulte transcricao.md para a conclusão corrigida; não usar este texto como reprovação vigente.
# Conferência humana recebida — 06/10/2026

O usuário exportou e entregou a conferência dos 22 áudios ativos, todos marcados `matches`, sem observações. O manifesto registra `reading_verified=true`, pseudônimo `revisor-01` e o horário informado no arquivo. A cópia versionável [conferencia-audios.json](conferencia-audios.json) preserva as marcações e substitui o nome do revisor por pseudônimo; o original permanece em outputs no workspace do chat.

Essa confirmação substitui o estado anterior de leituras não conferidas. Nenhum áudio, texto esperado, phrase_id ou exclusão foi alterado para favorecer um provedor. As evidências originais das rodadas foram preservadas.

As respostas de ambos os provedores para voz-a-r04 até voz-a-r08 continuam diferentes do texto esperado, embora a revisão humana declare correspondência entre áudio e referência. Registrar essa tensão de evidências: a hipótese anterior de remapeamento não foi confirmada pelo revisor e não autoriza corrigir os arquivos. Para revisão final do decisor, priorizar a conferência independente desses cinco casos e a atribuição dos erros; não ocultá-los nem usar concordância entre provedores como prova da fala.

A avaliação final ainda está incompleta. O validador do manifesto continua retornando 13 lacunas de cobertura: fala em WebM/WAV/MP4, oito controles de silêncio e ruído por formato, fala rápida e áudio longo. A página auxiliar outputs/gravar-avaliacao.html facilita a captura nativa dos formatos disponíveis; não garante suporte WAV/MP4 em todos os navegadores.

E1 segue sem execução bem-sucedida devido ao bloqueio de dependência pelo Controle de Aplicativo. Revisão de leitura não comprova extração ou acerto do ASR. ADR-007 permanece proposto, sem vencedor aceito.
