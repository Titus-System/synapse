package synapse.api.job;

import java.util.UUID;

import org.jspecify.annotations.Nullable;

/**
 * Forma de entrada do evento {@code etapa-alterada}
 * ({@code contracts/events/etapa-alterada.schema.json}). Payload vindo da fila: nada é
 * garantido em runtime, por isso todo componente é {@code @Nullable} - é o
 * {@link EtapaAlteradaConsumidor} quem valida antes de repassar ao SSE, nunca a
 * desserialização.
 */
record EtapaAlteradaDto(@Nullable UUID job_id, @Nullable String etapa, @Nullable String status) {
}
