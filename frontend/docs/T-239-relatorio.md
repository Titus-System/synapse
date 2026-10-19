# T-239 — Correção por voz no chatbot

## Base e escopo

Implementação sobre `synapse-commit(20261019-174320).zip`, commit-base `3454a48`.
Alterações apenas no frontend. API, contratos, banco e dependências npm preservados.

### Dependências encontradas

- **T-222:** o snapshot possui a rota e o visual do chatbot, mas a conversa é estática e o envio está desabilitado. Para a T-239 funcionar, esta entrega inclui a integração mínima de consulta das rodadas, envio por texto/voz, acompanhamento e bloqueios. Não afirma concluir todos os entregáveis da T-222.
- **T-229:** o componente visual existente foi preservado como referência. O arquivo/link oficial do mockup não veio no anexo. Os controles ficam junto ao texto no desktop e se empilham em telas estreitas. A comparação com Figma e a validação dessas adaptações pela PO continuam pendentes; não foram presumidas.
- **T-233:** captura e multipart já existem. A implementação de captura e seu componente foram promovidos para `src/composables/useGravacao.ts` e `src/components/EntradaVoz.vue`. Os caminhos anteriores são adaptadores para a mesma implementação, sem captura duplicada e sem necessidade de excluir arquivos ao aplicar o ZIP.
- **T-238:** há implementação na API para receber voz, iniciar `em_transcricao`, concluir a transcrição e reabrir uma pendente em falha. Foi inspecionada, não alterada nem executada.
- **T-226:** não havia histórico funcional integrado no chatbot do anexo. A renderização usa todas as rodadas retornadas, inclusive as de voz. Não foi implementada a retomada pela lista. Caso T-222/T-226 sejam integradas em paralelo, reconciliar os arquivos de conversa no rebase.

## Comportamento entregue

- Gravar, parar, ouvir, descartar, gravar novamente e enviar; máximo de três minutos e cinco MiB, reaproveitando a captura existente.
- Envio por `@/services/http`, com `FormData`: parte `audio` e parte JSON `parametros` (`finalidade: correcao`, `tipo: voz`, `job_id`). O navegador define o boundary.
- Entrada bloqueada durante envio, transcrição e interpretação. Áudio vazio e envio duplicado são recusados também na lógica do fluxo.
- Texto permanece visível e editável quando a rodada permite corrigir, inclusive enquanto se grava e diante de falha de microfone; o rascunho não é persistido. Durante processamento, fica temporariamente bloqueado junto da voz.
- Conversa reconstruída por `GET /jobs/{id}/rodadas`, no carregamento e na reconciliação do SSE. Eventos não são adicionados diretamente como mensagens.
- Espera de transcrição, texto de `correcao.texto` escapado pelo Vue e indicação “Correção por voz”, inclusive nas rodadas anteriores.
- Falha sem texto transcrito informa que não foi possível transcrever. Falha após transcrição informa que a correção não pôde ser aplicada. Nova pendente libera voz e texto.
- SSE e consulta de três em três segundos durante transcrição/reextração. A consulta periódica é necessária porque a API não publica SSE no sucesso da transcrição da correção; ela também recupera desfechos sem evento.
- Leituras e respostas antigas não sobrescrevem o próximo job nem uma submissão aceita. Navegação cancela HTTP, fecha SSE, limpa temporizadores, rascunho e contexto local.
- Microfone liberado ao parar; preview revogado ao descartar, enviar, trocar de job ou desmontar. Uma permissão concedida depois de sair é imediatamente liberada.
- Estados separados para falta de suporte, permissão negada e ausência de microfone. Botões nativos, foco visível, labels, `role=status`/`role=alert` e áudio com controles nativos.
- A tela de simulação oferece “Corrigir por texto ou voz” durante a espera de confirmação. A rota de correção verifica as rodadas: sem rodada aberta, retorna ao acompanhamento; jobs encerrados ficam somente para consulta.

## Validação executada

Ambiente: Node 24.19.0; npm 11.9.0. Os testes usam Vitest/jsdom, MediaRecorder simulado, respostas HTTP simuladas e callbacks de SSE simulados. Não houve chamada à API real nem ao provedor de transcrição.

| Comando/verificação | Resultado |
| --- | --- |
| `npm ci --ignore-scripts` | Instalação das dependências do lockfile concluída, sem alterar manifesto/lockfile |
| Testes dirigidos de serviço, composable, componentes e integração | Aprovados |
| `make check` dentro de `frontend/` | Aprovado: type-check, lint e **237 testes em 38 arquivos** |
| `sh verify.sh` dentro de `frontend/` | Aprovado: type-check, lint sem autofix, 237 testes e build Vite |
| `git diff --check` | Aprovado |
| Validação dos logs capturados em dois testes de integração | **11 registros** validados com `jsonschema.Draft202012Validator` e `FormatChecker` contra `contracts/observability/log.schema.json` |
| Conferência da fixture de voz | Igualdade com o exemplo `correcaoPorVozEmTranscricao` do OpenAPI, lido com PyYAML |

Foram corrigidas as falhas encontradas durante a implementação, incluindo a classificação de `DOMException` de microfone, tipos dos mocks e regras de lint. O quadro acima descreve o resultado final, não apenas a primeira tentativa.

### Cobertura relevante

Serviço: multipart autenticado, partes e parâmetros, boundary, resposta com voz, consulta e alternativa JSON de texto; falhas HTTP 400/409/413.

Composable: bloqueio de envio vazio e duplicado; rascunho; recarga em transcrição; passagem à interpretação sem SSE; transcrição falha seguida de nova pendente; reconexão/eventos repetidos; códigos de falha; texto inválido/válido; troca de job; envio e leitura atrasados; recuperação de leitura; desmontagem.

Captura/componentes: gravar/parar/prévia/enviar; descarte e troca de job; texto como alternativa; timeout de três minutos; ausência de suporte; permissão negada; ausência de microfone; áudio vazio ou acima do limite; erro do gravador; permissão e `onstop` tardios; escape de HTML; distinção de transcrição e interpretação; histórico de texto compatível.

Integração de frontend: view + composable + serviço + cliente HTTP real do projeto + gravador simulado, com `fetch` simulado. Confere bloqueio da tela, atualização da mensagem, reconciliação sem duplicação, falha da transcrição e falha no POST.

### Observabilidade

Operações de voz: `gravar_audio` e `enviar_correcao_voz`. A base de conversa também registra `ler_rodadas`, `enviar_correcao` e `conexao_correcao`, em conjunto fechado.

Registros incluem código sanitizado, resultado, duração em milissegundos e `job_id`. Sucesso, falha e cancelamento não recebem áudio, texto, motivos de conflitos, payload ou exceção bruta. A correlação é local à operação, não global; a troca de job descarta callbacks antigos e limpa o estado.

Os testes inspecionam registros serializados emitidos pelos fluxos reais do frontend. Não se limitam a verificar uma chamada a um mock do logger. A emissão foi validada; **coleta/exportação não foi validada**. O transporte existente é console JSON, sem exportador de telemetria. Não foram criados coletor nem métricas exportadas. `duracao_ms` é uma medida no log, não uma série Prometheus.

## Limites e verificações pendentes

- **Gravação real: nenhum navegador exercitado.** Não há navegador instalado neste ambiente; a instalação do Chromium pelo Playwright falhou por download inválido/truncado. Testes com gravador simulado não comprovam codec, permissão ou hardware reais.
- API real, SSE real, RabbitMQ, codegen e provedor de transcrição não foram executados. T-221/T-238 precisam ser verificadas no ambiente integrado.
- Layout em celular e operação completa por teclado precisam de conferência visual/manual no navegador. A estrutura é responsiva, mas jsdom não mede layout nem reproduz ativação nativa de botões pelo teclado.
- Comparação com o mockup T-229 e aceite da PO pendentes.
- Build de imagem Docker e CI remota não executados. O build Vite consta da verificação final.

Portanto, os gates automatizados locais estão atendidos; as verificações manuais e de integração externa acima permanecem abertas.

## Aplicação e comandos

Na raiz do repositório, antes de copiar os arquivos, confirme que `git status` está limpo. Não descarte alterações locais para trocar de branch.

```bash
git status
git switch develop
git pull --ff-only origin develop
git switch -c feature/t-239-correcao-voz
```

Extraia o ZIP na raiz do repositório, mesclando a pasta `frontend/`. Ele contém somente arquivos novos/modificados, com seus caminhos originais. Não copie `frontend` para dentro de outra pasta `frontend`. Se `develop` já tiver alterações nos mesmos arquivos desde o snapshot, concilie-as antes de prosseguir.

Comandos sem `make`, também adequados ao Git Bash no Windows:

```bash
cd frontend
npm ci
npm run type-check
npm run lint:verificar
npm run test:unit -- --run
npm run build-only
cd ..
git diff --check
git status --short
git diff --stat
git add frontend
git diff --cached --stat
git commit -m "feat(correction): permite corrigir a regra por voz" -m "Review: auto"
git push -u origin feature/t-239-correcao-voz
```

`git add frontend` pressupõe que apenas os arquivos desta entrega foram alterados. Confira o diff antes do commit. Use `Review: human` no lugar de `Review: auto` somente depois de efetivamente revisar e aprovar o diff. Abra o PR com destino a `develop`. Nenhum commit ou push foi realizado nesta entrega.

Alternativa de verificação no Git Bash: `cd frontend` e `sh verify.sh`. Com `make` instalado: `make check` e `npm run build-only`.

## Roteiro manual para completar a validação

1. Suba a API integrada com transcrição habilitada e o frontend (`npm run dev`). Use localhost ou HTTPS para permitir acesso ao microfone.
2. Abra uma regra com rodada pendente, pelo link “Corrigir por texto ou voz” ou `/jobs/<id>/correcao`.
3. Grave, pare e ouça. Envie e confira no Network as partes `audio`/`parametros`, `job_id` e `finalidade=correcao`.
4. Durante a transcrição, recarregue a página: o estado deve voltar pelo GET, com entrada bloqueada. Aguarde a transcrição e a indicação “Correção por voz”.
5. Exercite uma falha de transcrição no ambiente de teste; confira a mensagem e a nova tentativa por voz e texto.
6. Negue permissão, desconecte o microfone e teste navegador sem suporte. Confirme a alternativa por texto.
7. Grave e troque de job; confira que o indicador do microfone desliga e que a nova conversa não recebe conteúdo anterior.
8. Reconecte o SSE, teste Tab/Enter/Espaço e largura de 360 px. Confira ausência de mensagens duplicadas e sobreposição dos controles.
9. Inspecione apenas registros operacionais e confirme a ausência de conteúdo. Registre navegador/versão, sistema, resultado da gravação real e aceite visual da PO no PR.

## Arquivos do pacote

- `frontend/docs/T-239-relatorio.md`
- `frontend/src/components/EntradaVoz.spec.ts`
- `frontend/src/components/EntradaVoz.vue`
- `frontend/src/composables/useGravacao.spec.ts`
- `frontend/src/composables/useGravacao.ts`
- `frontend/src/features/correcao-regra/components/ConversaRodadas.spec.ts`
- `frontend/src/features/correcao-regra/components/ConversaRodadas.vue`
- `frontend/src/features/correcao-regra/components/EntradaCorrecao.spec.ts`
- `frontend/src/features/correcao-regra/components/EntradaCorrecao.vue`
- `frontend/src/features/correcao-regra/composables/useCorrecao.spec.ts`
- `frontend/src/features/correcao-regra/composables/useCorrecao.ts`
- `frontend/src/features/correcao-regra/services/correcao.api.spec.ts`
- `frontend/src/features/correcao-regra/services/correcao.api.ts`
- `frontend/src/features/correcao-regra/services/correcao.fixtures.ts`
- `frontend/src/features/correcao-regra/types.ts`
- `frontend/src/features/correcao-regra/views/CorrecaoRegraView.integration.spec.ts`
- `frontend/src/features/correcao-regra/views/CorrecaoRegraView.spec.ts`
- `frontend/src/features/correcao-regra/views/CorrecaoRegraView.vue`
- `frontend/src/features/entrada-regra/components/EntradaVoz.vue`
- `frontend/src/features/entrada-regra/composables/useGravacao.ts`
- `frontend/src/features/simulate/views/SimulateView.spec.ts`
- `frontend/src/features/simulate/views/SimulateView.vue`
- `frontend/src/observability/vozLogging.ts`
