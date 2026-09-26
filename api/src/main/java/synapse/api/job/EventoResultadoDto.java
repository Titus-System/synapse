package synapse.api.job;

import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.jspecify.annotations.Nullable;

/**
 * Forma do evento {@code resultado} do contrato HTTP ({@code EventoResultado}), entregue
 * ao stream SSE quando a simulação termina. Carrega a referência e o desfecho, nunca os
 * números - a tela busca {@code GET /jobs/{id}} e lê os valores de um lugar só.
 * {@code veredito} fica ausente do JSON quando nulo, nunca presente como {@code null}: o
 * schema o declara ausente fora de {@code status: sucesso}.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record EventoResultadoDto(UUID job_id, UUID simulacao_id, String status, @Nullable String veredito) {
}
