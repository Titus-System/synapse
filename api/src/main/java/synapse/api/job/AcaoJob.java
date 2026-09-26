package synapse.api.job;

import java.util.Locale;

/**
 * As quatro ações de finalização do contrato HTTP ({@code AcaoJob}), no mesmo vocabulário
 * da coluna {@code job_acoes.acao}. {@code SALVAR} é sinônimo de
 * {@code CONFIRMAR_LIBERAR}: não existe estado "salvo" na máquina de estados, e as duas
 * levam a {@link JobStatus#LIBERADO} sob a mesma recusa quando a simulação é inviável.
 */
enum AcaoJob {

	CONFIRMAR_LIBERAR(JobStatus.LIBERADO), CANCELAR(JobStatus.CANCELADO), SALVAR(JobStatus.LIBERADO),
	ARQUIVAR(JobStatus.ARQUIVADO);

	private final JobStatus destino;

	AcaoJob(JobStatus destino) {
		this.destino = destino;
	}

	JobStatus destino() {
		return this.destino;
	}

	String paraColuna() {
		return name().toLowerCase(Locale.ROOT);
	}

	static AcaoJob deColuna(String valor) {
		return AcaoJob.valueOf(valor.toUpperCase(Locale.ROOT));
	}

}
