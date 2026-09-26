package synapse.api.job;

import java.util.Objects;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.SimulacaoConcluidaService.DesfechoAplicado;

@Component
class SimulacaoConcluidaConsumidor {

	private static final Logger log = LoggerFactory.getLogger(SimulacaoConcluidaConsumidor.class);

	private final SimulacaoConcluidaService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	SimulacaoConcluidaConsumidor(SimulacaoConcluidaService servico, EmissoresSse emissores,
			CorrelationContext correlacao) {
		this.servico = servico;
		this.emissores = emissores;
		this.correlacao = correlacao;
	}

	@RabbitListener(queues = RabbitTopologyConfig.SIMULACAO_CONCLUIDA_API)
	void receber(SimulacaoConcluidaDto evento) {
		UUID jobId = evento.job_id();
		UUID resultadoId = evento.resultado_id();
		if (jobId == null || resultadoId == null) {
			log.atWarn().log("simulacao-concluida sem job_id ou resultado_id; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			DesfechoDaSimulacao desfecho = DesfechoDaSimulacao.de(evento.status(), evento.veredito());
			if (desfecho == null) {
				log.atWarn()
					.addKeyValue("status", evento.status())
					.log("simulacao-concluida com status ou veredito desconhecido; evento descartado");
				return;
			}

			DesfechoAplicado aplicado;
			try {
				aplicado = this.servico.aplicar(jobId, resultadoId, desfecho);
			}
			catch (TransicaoDeStatusInvalidaException ex) {
				log.atWarn()
					.addKeyValue("resultado_id", resultadoId)
					.setCause(ex)
					.log("simulacao-concluida não aplicada; job fora do estado de origem esperado (reentrega ou evento fora de ordem)");
				return;
			}

			if (aplicado == null) {
				log.atWarn()
					.addKeyValue("resultado_id", resultadoId)
					.log("resultado descartado: não pertence à versão atual do job");
				return;
			}

			if (aplicado.avancouDeGerandoRegra()) {
				this.emissores.emitir(jobId, EventoSse.de("estado",
						EventoEstadoDto.transicao(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, null)));
			}

			// "resultado" sai antes de "estado" (skill sse): um "estado" terminal fecha
			// o stream, e o que viesse depois se perderia.
			UUID simulacaoId = aplicado.simulacaoId();
			if (simulacaoId != null) {
				// desfecho != null garante que evento.status() não é nulo (ver
				// DesfechoDaSimulacao.de).
				String status = Objects.requireNonNull(evento.status());
				// O veredito só existe no contrato quando status = sucesso (openapi,
				// EventoResultado); um valor presente por engano num status de erro é
				// descartado aqui, na mesma decisão que DesfechoDaSimulacao.de já toma
				// para a transição - nunca repassado cru do evento não confiável.
				String veredito = "sucesso".equals(status) ? evento.veredito() : null;
				this.emissores.emitir(jobId,
						EventoSse.de("resultado", new EventoResultadoDto(jobId, simulacaoId, status, veredito)));
			}

			JobStatus destino = desfecho.destino();
			EventoEstadoDto eventoEstado = EventoEstadoDto.transicao(jobId, aplicado.origem(), destino,
					desfecho.razaoLocalizada());
			EventoSse eventoSse = destino.terminal() ? EventoSse.ultimo("estado", eventoEstado)
					: EventoSse.de("estado", eventoEstado);
			this.emissores.emitir(jobId, eventoSse);
			log.atDebug().addKeyValue("status", destino.paraColuna()).log("simulacao-concluida aplicada");
		}
	}

}
