# Complementos MP4 — 06/10/2026

Recebidos dois arquivos pela página de captura, voz-a/r01/office_noise e voz-b/r01/fast. Incorporados às fixtures sem conversão, com SHA-256, tamanho e duração medida pelo campo mvhd do contêiner MP4 (7,40 s e 6,44 s). O contêiner contém identificação Opus. Metadados completos de navegador/versão e conferência humana das novas leituras ainda não entregues. O rótulo de condição vem do nome escolhido na captura, não de medição de ruído ou velocidade.

[Respostas reais](complementos-mp4-20261006-141623.json): uma tentativa por arquivo/candidato, quatro HTTP 200.

| Condição | Deepgram Nova-3 | Groq whisper-large-v3 |
| --- | --- | --- |
| Ruído de escritório | 3.930 ms | 478 ms |
| Fala rápida | 925 ms | 628 ms |

Deepgram retornou nas duas chamadas `na loja treze a comissão da marca dez para o cargo cem será de dois vírgula cinco por cento`. Groq retornou nas duas chamadas `Na loja 13, a comissão da marca 10 para o cargo 100 será de 2,5%.` Nessa comparação textual, ambos preservam os quatro elementos esperados da frase r01; não é validação auditiva nem comprovação de compatibilidade com E1. Não extrapolar dois casos para todo o corpus ou todo codec MP4.

Comando executado: `& ../work/coletar-complementos.ps1`, na raiz do repositório (script auxiliar no workspace do chat). Helpers reutilizados do coletor; sem prompt da frase esperada, sem conversão, com conferência de hash e interrupção por autorização/quota. Manifesto validado: 24 gravações ativas, 713.664 bytes, conjunto ainda incompleto com 11 lacunas. `git diff --check` passou.

Faltam fala WebM/WAV, oito controles sem fala por formato e condição, áudio longo, informações de captura e revisão de duas novas leituras. E1 e decisão final permanecem pendentes. Sucesso MP4 e fala rápida substituem essas lacunas anteriormente registradas; demais ressalvas das rodadas anteriores permanecem.
