package synapse.api.job;

import java.util.UUID;

/** Não existe job com o identificador informado. */
class JobNaoEncontradoException extends RuntimeException {

	JobNaoEncontradoException(UUID jobId) {
		super("Job não encontrado: " + jobId);
	}

}
