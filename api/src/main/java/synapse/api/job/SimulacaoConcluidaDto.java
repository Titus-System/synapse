package synapse.api.job;

import java.math.BigDecimal;
import java.util.UUID;

import org.jspecify.annotations.Nullable;

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
