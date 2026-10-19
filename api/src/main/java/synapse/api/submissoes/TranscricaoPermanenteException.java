package synapse.api.submissoes;

class TranscricaoPermanenteException extends RuntimeException {

	TranscricaoPermanenteException() {
		super("Falha permanente na transcrição.");
	}

}
