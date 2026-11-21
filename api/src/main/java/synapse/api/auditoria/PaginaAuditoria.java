package synapse.api.auditoria;

/** Paginação de {@code GET /auditoria/jobs}, com os limites de {@code GET /jobs}. */
record PaginaAuditoria(int pagina, int tamanho) {

	static final int TAMANHO_MAXIMO = 100;

	PaginaAuditoria {
		if (pagina < 0) {
			throw RequisicaoInvalidaNaAuditoriaException.pagina();
		}
		if (tamanho < 1 || tamanho > TAMANHO_MAXIMO) {
			throw RequisicaoInvalidaNaAuditoriaException.tamanho();
		}
	}

	long deslocamento() {
		return (long) this.pagina * this.tamanho;
	}

}
