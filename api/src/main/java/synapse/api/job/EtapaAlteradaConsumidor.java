package synapse.api.job;

import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;

/**
 * Consome {@code etapa-alterada}, aplica a transição de estado que a etapa implica
 * ({@link EtapaAlteradaService}) e repassa ao stream SSE do job, traduzido para
 * {@link EventoEtapaDto}. Não deduplica por {@code message_id}, que este evento não
 * carrega: uma reentrega encontra o job já fora de {@code gerando_regra} e a transição
 * vira no-op. Nunca lança em entrada inválida: vira descarte com log {@code WARN}, porque
 * uma exceção aqui viraria requeue infinito.
 */
@Component
class EtapaAlteradaConsumidor {

	private static final Logger log = LoggerFactory.getLogger(EtapaAlteradaConsumidor.class);

	private final EtapaAlteradaService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	EtapaAlteradaConsumidor(EtapaAlteradaService servico, EmissoresSse emissores, CorrelationContext correlacao) {
		this.servico = servico;
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

			EventoEstadoDto transicao;
			try {
				transicao = this.servico.aplicar(jobId, etapa, status);
			}
			catch (EmptyResultDataAccessException ex) {
				log.atWarn().setCause(ex).log("etapa-alterada de job desconhecido; evento descartado");
				return;
			}

			// "etapa" sai antes de "estado" (skill sse): um "estado" terminal fecha o
			// stream.
			this.emissores.emitir(jobId, EventoSse.de("etapa", new EventoEtapaDto(jobId, etapa.paraEvento(), status)));
			if (transicao != null) {
				boolean terminal = JobStatus.deColuna(transicao.status()).terminal();
				this.emissores.emitir(jobId,
						terminal ? EventoSse.ultimo("estado", transicao) : EventoSse.de("estado", transicao));
			}
			log.atDebug().addKeyValue("etapa", etapa.paraEvento()).log("etapa repassada ao stream SSE");
		}
	}

}
