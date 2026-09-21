package synapse.api.job;

import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;

/**
 * Consome {@code etapa-alterada} e repassa ao stream SSE do job correspondente, traduzido
 * para {@link EventoEtapaDto}. Não deduplica: é uma exceção deliberada à regra de
 * idempotência dos consumidores de fila (`api/AGENTS.md`) - o evento é puramente
 * informativo, sem efeito de estado nem financeiro, e nem carrega {@code message_id} (o
 * codegen só o define para {@code no-concluido}). Nunca lança: toda entrada inválida vira
 * descarte com log {@code WARN}, porque uma exceção aqui viraria requeue infinito.
 */
@Component
class EtapaAlteradaConsumidor {

	private static final Logger log = LoggerFactory.getLogger(EtapaAlteradaConsumidor.class);

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	EtapaAlteradaConsumidor(EmissoresSse emissores, CorrelationContext correlacao) {
		this.emissores = emissores;
		this.correlacao = correlacao;
	}

	@RabbitListener(queues = RabbitTopologyConfig.ETAPA_ALTERADA)
	void receber(EtapaAlteradaDto evento) {
		UUID jobId = evento.job_id();
		if (jobId == null) {
			log.atWarn().log("etapa-alterada sem job_id; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			EtapaDoGrafo etapa = EtapaDoGrafo.deEvento(evento.etapa());
			String status = evento.status();
			if (etapa == null || !StringUtils.hasText(status)) {
				log.atWarn()
					.addKeyValue("etapa", evento.etapa())
					.log("etapa-alterada com etapa desconhecida; evento descartado");
				return;
			}

			this.emissores.emitir(jobId, EventoSse.de("etapa", new EventoEtapaDto(jobId, etapa.paraEvento(), status)));
			log.atDebug().addKeyValue("etapa", etapa.paraEvento()).log("etapa repassada ao stream SSE");
		}
	}

}
