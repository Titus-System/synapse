package synapse.api.job;

import java.util.Objects;
import java.util.UUID;

import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;

@Service
class AcompanharJobService {

	private final EmissoresSse emissores;

	private final JdbcTemplate jdbcTemplate;

	AcompanharJobService(EmissoresSse emissores, JdbcTemplate jdbcTemplate) {
		this.emissores = emissores;
		this.jdbcTemplate = jdbcTemplate;
	}

	/**
	 * Abre o stream de {@code jobId}. A fotografia é lida uma única vez, sob a trava de
	 * {@link EmissoresSse#inscrever}: se o job não existir,
	 * {@link JobNaoEncontradoException} propaga e nenhum emissor fica registrado - a
	 * requisição responde 404 em vez de virar stream.
	 */
	SseEmitter acompanhar(UUID jobId) {
		return this.emissores.inscrever(jobId, () -> fotografia(jobId));
	}

	private EventoSse fotografia(UUID jobId) {
		JobStatus status = statusAtual(jobId);
		EventoEstadoDto evento = EventoEstadoDto.fotografia(jobId, status);
		return status.terminal() ? EventoSse.ultimo("estado", evento) : EventoSse.de("estado", evento);
	}

	private JobStatus statusAtual(UUID jobId) {
		try {
			String status = Objects.requireNonNull(
					this.jdbcTemplate.queryForObject("SELECT status FROM jobs WHERE id = ?", String.class, jobId));
			return JobStatus.deColuna(status);
		}
		catch (EmptyResultDataAccessException ex) {
			throw new JobNaoEncontradoException(jobId);
		}
	}

}
