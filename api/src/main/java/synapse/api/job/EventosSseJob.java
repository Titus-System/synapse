package synapse.api.job;

import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.jspecify.annotations.Nullable;

/**
 * Forma do evento {@code estado} do contrato HTTP ({@code EventoEstado}). A mesma forma
 * abre toda conexão ao stream, como fotografia do estado atual, e também anuncia cada
 * transição daí em diante. {@code status_anterior} e {@code motivo} ficam ausentes do
 * JSON quando nulos, nunca presentes como {@code null} - a fotografia e a transição
 * inicial não têm status anterior.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record EventoEstadoDto(UUID job_id, String status, @Nullable String status_anterior, @Nullable String motivo) {

	static EventoEstadoDto fotografia(UUID jobId, JobStatus status) {
		return new EventoEstadoDto(jobId, status.paraColuna(), null, null);
	}

	static EventoEstadoDto transicao(UUID jobId, JobStatus origem, JobStatus destino, @Nullable String motivo) {
		return new EventoEstadoDto(jobId, destino.paraColuna(), origem.paraColuna(), motivo);
	}

}

/**
 * Forma do evento {@code etapa} do contrato HTTP ({@code EventoEtapa}), entregue ao
 * stream SSE. Mesmos três campos de {@link EtapaAlteradaDto}, e ainda assim um record
 * separado: são dois contratos distintos - fila de entrada e HTTP de saída -, e é a
 * separação que impede um campo novo publicado pelo codegen de vazar sozinho para o
 * navegador.
 */
record EventoEtapaDto(UUID job_id, String etapa, String status) {
}

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
