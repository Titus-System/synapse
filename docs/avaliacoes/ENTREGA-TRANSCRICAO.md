# Roteiro para concluir a avaliação de transcrição

Conferência local em 06/10/2026. O ADR-007 permanece proposto: ainda não há respostas reais dos provedores. Não declarar a tarefa concluída antes da avaliação e revisão do decisor.

## 1. Conferir os áudios existentes

Ouvir as 22 gravações ativas e comparar com `expected_text` em `api/src/test/resources/transcricao/gravacoes.json`. Registrar divergências, inclusive número, código, exclusão ou palavra omitida. Corrigir a referência para a fala realmente autorizada ou regravar; não marcar `reading_verified=true` sem ouvir. A frase r09 já está excluída no manifesto; preservar esse recorte até confirmação do responsável.

Confirmar com as duas pessoas a autorização para versionamento e processamento externo. As referências atuais citam uma conversa anterior não verificada nesta sessão. Registrar a referência verdadeira ao comprovante, sem inventar consentimento ou expor dados pessoais.

## 2. Complementar o conjunto

- Fala capturada no navegador em WebM, WAV e MP4, se o navegador realmente produzir cada formato. Não converter Ogg nem trocar extensões para simular captura.
- Uma leitura em velocidade rápida.
- Oito controles sem fala: silêncio e ruído de escritório em cada formato WebM, Ogg, WAV e MP4.
- Uma leitura de 165 a 180 segundos para medir latência próxima do limite.
- Registrar navegador/versão, codec, duração, hash e tamanho conforme o README das fixtures. Se a captura nativa de algum formato não for possível, registrar esse achado para decisão sobre T-230.

O manifesto tem 22 áudios ativos e 487.838 bytes. O validador atual lista 13 lacunas de cobertura. A tarefa exige pelo menos dez frases e duas pessoas; o recorte atual tem 11 frases em duas vozes, mas a leitura ainda não foi conferida.

## 3. Configurar as contas

Usar contas de API na Deepgram e OpenAI. Configurar `DEEPGRAM_API_KEY` e `OPENAI_API_KEY` no ambiente do processo que executará a coleta. Não salvar segredos no repositório nem enviá-los em mensagens. Após mudar variáveis de usuário, abrir um novo terminal para herdá-las. Confirmar tarifas, crédito, região e opções de dados no painel antes da coleta; a estimativa do script não é uma fatura.

## 4. Executar na raiz do projeto

```powershell
& ./api/scripts/avaliar-transcricao.ps1 -Mode corpus
& ./api/scripts/avaliar-transcricao.ps1 -Mode autoteste
& ./api/scripts/test-avaliar-transcricao.ps1
& ./api/scripts/avaliar-transcricao.ps1 -Mode gravacoes
& ./api/scripts/coletar-transcricao.ps1 -Mode planejar
```

Prosseguir somente quando `ready_for_collection=true`. O coletor bloqueia conjunto incompleto, leitura sem conferência e credenciais ausentes.

```powershell
& ./api/scripts/coletar-transcricao.ps1 -Mode coletar -ResultsPath docs/avaliacoes/rodada-transcricao.json
```

O arquivo de saída precisa não existir. O coletor preserva cada tentativa, intercala candidatos, mede tempo incluindo upload e não faz conversão de áudio. Ele pode gerar cobrança. São três tentativas por arquivo por candidato; o recorte atual planeja 132 chamadas, mas esse número aumentará com os controles adicionais.

## 5. Revisar e consolidar

No JSON da rodada, revisar cada resposta contra o áudio. Preencher `reviewed_by`, `unexpected_elements` e todas as `annotations`: `correct`, `representation` e `evidence`. Não confundir saída em algarismos com erro semântico, nem aceitar valor certo associado ao alvo errado. Conferir separadamente a compatibilidade com E1; a agregação offline não executa o codegen.

```powershell
& ./api/scripts/avaliar-transcricao.ps1 -Mode resultados -ResultsPath docs/avaliacoes/rodada-transcricao.json
```

Copiar métricas observadas para `transcricao.md`, incluindo erros e recusas. Atualizar ADR-007 com vencedor, motivos, alternativas, política de dados e pendências da PO. Submeter ao decisor. Registrar a decisão na T-235 e eventual mudança na T-230; não implementar cliente ou alteração de contrato nesta tarefa.

## Verificação desta sessão

Corpus validado: 12 frases e 44 elementos. Autoteste: 9 casos aprovados. Testes de manifesto e agregação: 11 cenários aprovados. Planejamento executado sem chamadas externas; duas credenciais ausentes, 22 leituras pendentes e conjunto incompleto. Nenhum teste real de reconhecimento, E1, latência, cobrança ou revisão do decisor foi executado. Os testes sintéticos não comprovam qualidade de transcrição.
