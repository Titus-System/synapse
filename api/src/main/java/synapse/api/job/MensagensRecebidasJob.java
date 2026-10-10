package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import tools.jackson.databind.JsonNode;

/**
 * Forma de entrada do evento {@code etapa-alterada}
 * ({@code contracts/events/etapa-alterada.schema.json}). Payload vindo da fila: nada é
 * garantido em runtime, por isso todo componente é {@code @Nullable} - é o
 * {@link EtapaAlteradaConsumidor} quem valida antes de repassar ao SSE, nunca a
 * desserialização.
 */
record EtapaAlteradaDto(@Nullable UUID job_id, @Nullable String etapa, @Nullable String status,
		@Nullable String causa) {
}

/**
 * Forma de entrada do evento {@code no-concluido}
 * ({@code contracts/events/no-concluido.schema.json}). Payload vindo da fila: nada é
 * garantido em runtime, por isso todo componente é {@code @Nullable} - é o
 * {@link NoConcluidoConsumidor} quem valida antes de gravar, nunca a desserialização.
 * {@code conclusao} fica como {@link JsonNode} porque sua forma varia por nó (contrato em
 * {@code contracts/domain/trilha-conclusao.schema.json}) e a api só a persiste, nunca a
 * interpreta.
 */
record NoConcluidoDto(@Nullable UUID evento_id, @Nullable UUID job_id, @Nullable String no,
		@Nullable Instant concluido_em, @Nullable JsonNode conclusao, @Nullable UUID regra_id,
		@Nullable UUID simulacao_id, @Nullable UUID prompt_id, @Nullable UUID codigo_gerado_id,
		@Nullable UUID explicacao_id) {
}

/**
 * Forma de entrada do evento {@code simulacao-concluida}
 * ({@code contracts/events/simulacao-concluida.schema.json}). Payload vindo da fila: nada
 * é garantido em runtime, por isso todo componente é {@code @Nullable} - é
 * {@link SimulacaoConcluidaConsumidor} quem valida antes de aplicar, nunca a
 * desserialização.
 *
 * <p>
 * Os quatro totais não são usados por nenhum caminho da api - o contrato do stream SSE é
 * explícito ao dizer que o evento {@code resultado} carrega a referência e o desfecho,
 * não os números. Eles entram no DTO para que uma mudança de tipo no schema quebre
 * {@code ExemplosDeContratoTests} em vez de passar despercebida.
 */
record SimulacaoConcluidaDto(@Nullable UUID job_id, @Nullable UUID resultado_id, @Nullable String status,
		@Nullable String veredito, @Nullable BigDecimal total_baseline, @Nullable BigDecimal total_simulado,
		@Nullable BigDecimal diferenca_abs, @Nullable BigDecimal diferenca_pct) {
}

/**
 * Forma de entrada do evento {@code sugestao-adaptacao-proposta}
 * ({@code contracts/events/sugestao-adaptacao-proposta.schema.json}). Payload vindo da
 * fila: nada é garantido em runtime, por isso todo componente é {@code @Nullable} - é
 * {@link SugestaoAdaptacaoConsumidor} quem valida antes de gravar, nunca a
 * desserialização.
 *
 * <p>
 * {@code representacao} vem no corpo, e não por referência, porque a linha de
 * {@code regras} que a guardaria é justamente o que este evento pede para criar. A api é
 * dona da numeração da versão, do hash canônico e do estado do job (AGENTS.md).
 */
record SugestaoAdaptacaoPropostaDto(@Nullable UUID job_id, @Nullable UUID regra_origem_id, @Nullable UUID resultado_id,
		@Nullable RepresentacaoRegraDto representacao) {
}

/**
 * Forma de entrada do evento {@code regra-extraida}
 * ({@code contracts/events/regra-extraida.schema.json}). Payload vindo da fila: nada é
 * garantido em runtime, por isso todo componente é {@code @Nullable} - é
 * {@link RegraExtraidaConsumidor} quem valida antes de gravar, nunca a desserialização.
 * Só referências viajam (ADR-001): a representação fica em {@code extracoes_regras}, de
 * onde a api a lê pelo {@code extracao_id}.
 */
record RegraExtraidaDto(@Nullable UUID job_id, @Nullable UUID submissao_id, @Nullable UUID extracao_id) {
}
