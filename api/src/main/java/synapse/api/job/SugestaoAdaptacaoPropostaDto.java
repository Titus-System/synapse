package synapse.api.job;

import java.util.UUID;

import org.jspecify.annotations.Nullable;

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
