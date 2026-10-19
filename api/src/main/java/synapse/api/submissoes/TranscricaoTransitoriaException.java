package synapse.api.submissoes;

import java.time.Duration;

class TranscricaoTransitoriaException extends RuntimeException {

	private final Duration prazoParaNovaTentativa;

	private final boolean respostaInvalida;

	TranscricaoTransitoriaException(Duration prazoParaNovaTentativa, boolean respostaInvalida) {
		super("Falha transitória na transcrição.");
		this.prazoParaNovaTentativa = prazoParaNovaTentativa;
		this.respostaInvalida = respostaInvalida;
	}

	Duration prazoParaNovaTentativa() {
		return this.prazoParaNovaTentativa;
	}

	boolean respostaInvalida() {
		return this.respostaInvalida;
	}

}
