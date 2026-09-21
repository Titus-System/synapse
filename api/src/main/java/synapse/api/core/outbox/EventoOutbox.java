package synapse.api.core.outbox;

import synapse.api.core.messaging.RabbitTopologyConfig;

/**
 * Eventos que a api publica pelo outbox. O nome do evento é também o da fila que o
 * carrega (DEC-089), e é o que vai para {@code outbox_events.tipo}.
 */
public enum EventoOutbox {

	REGRA_SUBMETIDA(RabbitTopologyConfig.REGRA_SUBMETIDA),

	PARAMETROS_CONFIRMADOS(RabbitTopologyConfig.PARAMETROS_CONFIRMADOS);

	private final String tipo;

	EventoOutbox(String tipo) {
		this.tipo = tipo;
	}

	public String tipo() {
		return this.tipo;
	}

}
