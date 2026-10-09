package synapse.api.submissoes;

import org.springframework.stereotype.Component;

/** A T-235 liga esta consulta à configuração do cliente concreto de transcrição. */
@Component
class DisponibilidadeTranscricao {

	boolean disponivel() {
		return false;
	}

}
