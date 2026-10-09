package synapse.api.submissoes;

import org.springframework.stereotype.Component;

@Component
class DisponibilidadeTranscricao {

	private final ClienteDeepgram cliente;

	DisponibilidadeTranscricao(ClienteDeepgram cliente) {
		this.cliente = cliente;
	}

	boolean disponivel() {
		return this.cliente.configurado();
	}

}
