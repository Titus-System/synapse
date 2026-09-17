 T-072 — Cliente SSE com reconexão e deduplicação

 Contexto

 T-072 pede a camada de transporte do frontend que abre GET /jobs/{id}/events
 (SSE), reconecta sozinha com recuo progressivo, deduplica eventos repetidos e
 reconcilia o estado por GET /jobs/{id} na reconexão. É pura infraestrutura —
 sem telas: T-073 (progresso) e T-075 (resultado) consomem o que este trabalho
 entrega à store do job.

 Branch já criada a partir de develop (que já contém T-071, mergeada):
 feature/t-072-sse-client.

 Estado já existente (T-071, mergeado em develop):
 - src/services/api.ts — apiClient.acompanharJob(id) já existe e só
   devolve a URL tipada do stream; abrir/consumir a conexão é explicitamente
   atribuído a T-072 em src/services/README.md:19.
 - src/services/http.ts — cliente REST, com HttpError e mapeamento de erro.
 - src/stores/currentJob.ts — store Pinia esboço (usarStoreJobAtual), só
   com idJob, comentário dizendo que REST/SSE entram depois.
 - src/types/api.ts — tipos do contrato REST (Job, StatusJob etc.), mas
   sem os tipos dos eventos do stream (EventoEtapa/EventoEstado/
   EventoResultado).

 Contrato (contracts/http/openapi.yaml, GET /jobs/{id}/events, ~L315-389
 e schemas EventoProgresso/EventoEtapa/EventoEstado/EventoResultado,
 ~L1209-1307):
 - Enquadramento SSE explícito: cada evento tem só uma linha event: (nome:
   etapa | estado | resultado) e uma linha data: (JSON). O exemplo
   oficial não usa linha id: — não há identificador sequencial fornecido
   pelo servidor no contrato atual.
 - Ao conectar (inicial ou reconexão), o primeiro evento é sempre estado com
   a fotografia atual.
 - resultado anuncia o desfecho mas não os números — cliente busca
   GET /jobs/{id} para ler valores.
 - O stream fecha sozinho após o estado que anuncia um estado terminal
   (liberado, cancelado, arquivado, erro); reabrir um job terminal
   devolve a fotografia e fecha de novo.
 - Reconexão: "o cliente reabre a mesma requisição e recebe de novo a
   fotografia do estado atual" — não fala de replay de eventos perdidos além
   disso.

 Decisão de design — deduplicação sem id sequencial do servidor. A tarefa e
 a arquitetura pedem "deduplicação de eventos"/"identificador sequencial", mas
 o contrato real (fonte de verdade, já que T-043/servidor ainda não está
 implementado) não emite um. Em vez de bloquear a tarefa por isso, a
 implementação usa dois mecanismos que cobrem o critério de aceite ("o mesmo
 evento entregue duas vezes não produz efeito duplicado") sem depender de um
 campo que não existe:
 1. Aplicação idempotente por natureza: estado/etapa atualizam refs
    escalares (last-write-wins) na store, nunca uma lista que cresce — repetir
    o mesmo evento não duplica nada visível.
 2. Chave de negócio para o único efeito colateral: resultado dispara um
    GET /jobs/{id}; a store guarda o último simulacao_id já processado e
    ignora um resultado repetido com o mesmo id, evitando fetch duplicado.
 3. Se o servidor um dia passar a mandar id: (framing SSE, não exige mudar o
    schema JSON em contracts/), o EventSource nativo já expõe isso via
    lastEventId — não é usado agora porque não há hoje o que deduplicar por
    ele, mas nada no design impede adicionar depois.

 Isso não é edição de contrato (nenhum arquivo em contracts/ muda) — é uma
 leitura literal do que já está publicado.

 Plano de implementação

 1. Tipos (src/types/api.ts)

 Adicionar, ao lado dos tipos de Job já existentes, os três formatos de
 evento do stream, espelhando os schemas do openapi (job_id, etapa,
 status, status_anterior?, motivo?, simulacao_id, veredito?):
 EventoEtapa, EventoEstado, EventoResultado.

 2. Serviço SSE (src/services/jobEvents.ts, novo)

 Um único módulo (sem generalizar num sse.ts genérico — há um único stream
 no app hoje; YAGNI) expondo:

 function abrirAcompanhamentoJob(idJob: string, handlers: {
   onEstado(e: EventoEstado): void
   onEtapa(e: EventoEtapa): void
   onResultado(e: EventoResultado): void
   onReconciliar(job: Job): void
   onStatusConexao(status: 'conectando' | 'aberta' | 'reconectando'): void
 }): { fechar(): void }

 Responsabilidades internas:
 - Usa apiClient.acompanharJob(idJob) para a URL e new EventSource(url)
   (via globalThis.EventSource para ser mockável em teste, igual ao padrão
   já usado com fetch em http.spec.ts/api.spec.ts).
 - addEventListener('etapa'|'estado'|'resultado', ...) — usa o mecanismo
   nativo de eventos nomeados do EventSource, que já casa com o
   enquadramento do contrato.
 - Reconexão manual com recuo progressivo: no onerror, fecha a instância
   nativa (close()) e agenda setTimeout com backoff exponencial (base
   1000ms, fator 2, teto 30000ms, com jitter pequeno) antes de abrir uma
   EventSource nova — não depende do retry automático do browser, que não
   tem backoff configurável a partir do cliente.
 - Conta tentativas; a partir da 2ª abertura (reconexão de verdade, não a
   conexão inicial) chama apiClient.consultarJob(idJob) e repassa o
   resultado a onReconciliar. Reseta o contador de tentativas em onopen.
 - Erro da reconciliação REST é engolido (best-effort): o próximo evento
   estado do stream ainda mantém a UI consistente.
 - fechar() cancela timer pendente e fecha a conexão nativa — cobre "sair da
   tela encerra o stream".

 3. Store (src/stores/currentJob.ts)

 Substituir o esboço por: idJob, job (Job | null), statusAtual,
 statusAnterior?, motivoParada?, etapaAtual ({ etapa, status } | null),
 estadoConexao, e as ações iniciarAcompanhamento(id) /
 pararAcompanhamento() que chamam abrirAcompanhamentoJob e escrevem nos
 refs acima. iniciarAcompanhamento reseta o simulacao_id já processado.
 Sem cálculo/derivação — só atribuição direta dos campos que chegam da API,
 conforme a regra de segurança do frontend.

 4. Testes

 - src/services/jobEvents.spec.ts: EventSource fake instalada via
   vi.stubGlobal, com addEventListener/close/onerror/onopen
   simuláveis manualmente. Cobre: despacho dos 3 tipos de evento; abertura
   fecha e reabre com backoff crescente após onerror (fake timers); GET de
   reconciliação só a partir da 2ª conexão; fechar() impede nova tentativa
   agendada.
 - src/stores/currentJob.spec.ts (ou extensão de stores/stores.spec.ts,
   confirmar convenção do arquivo existente ao implementar): duplicar o mesmo
   resultado (mesmo simulacao_id) e verificar uma única chamada a
   apiClient.consultarJob; verificar que pararAcompanhamento fecha a
   conexão simulada.

 5. Verificação

 Rodar make check (type-check + lint + test) em frontend/, conforme
 frontend/AGENTS.md. Reportar o resultado ao final.

 Fora do escopo (não mexer)

 - Infra SSE do servidor (T-043, ainda não implementada).
 - Telas de progresso (T-073) e resultado (T-075).
 - Qualquer alteração em contracts/.
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
