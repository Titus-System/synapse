package synapse.api.job;

import java.time.Instant;
import java.util.UUID;

import tools.jackson.databind.JsonNode;

import org.jspecify.annotations.Nullable;

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
