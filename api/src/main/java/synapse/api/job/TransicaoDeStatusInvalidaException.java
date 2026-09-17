package synapse.api.job;

/**
 * Uma transição fora do grafo declarado em {@link JobStatus}: evento fora de ordem ou
 * ação do usuário incompatível com o status atual do job.
 */
public class TransicaoDeStatusInvalidaException extends RuntimeException {

	public TransicaoDeStatusInvalidaException(JobStatus origem, JobStatus destino) {
		super("Transição de %s para %s não é permitida.".formatted(origem, destino));
	}

}
