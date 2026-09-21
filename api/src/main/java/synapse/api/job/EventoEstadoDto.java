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
