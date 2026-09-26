package synapse.api.job;

import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.SugestaoAdaptacaoService.SugestaoAplicada;

@Component
class SugestaoAdaptacaoConsumidor {

	private static final Logger log = LoggerFactory.getLogger(SugestaoAdaptacaoConsumidor.class);

	private final SugestaoAdaptacaoService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	SugestaoAdaptacaoConsumidor(SugestaoAdaptacaoService servico, EmissoresSse emissores,
			CorrelationContext correlacao) {
		this.servico = servico;
		this.emissores = emissores;
		this.correlacao = correlacao;
	}

	@RabbitListener(queues = RabbitTopologyConfig.SUGESTAO_ADAPTACAO_PROPOSTA)
	void receber(SugestaoAdaptacaoPropostaDto evento) {
		UUID jobId = evento.job_id();
		UUID regraOrigemId = evento.regra_origem_id();
		UUID resultadoId = evento.resultado_id();
		RepresentacaoRegraDto representacao = evento.representacao();
		if (jobId == null || regraOrigemId == null || resultadoId == null || representacao == null
				|| representacao.nucleo() == null || representacao.especificacoes() == null) {
			log.atWarn().log("sugestao-adaptacao-proposta incompleta; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			SugestaoAplicada aplicada;
			try {
				aplicada = this.servico.aplicar(jobId, regraOrigemId, resultadoId, representacao);
			}
			catch (TransicaoDeStatusInvalidaException ex) {
				log.atWarn()
					.setCause(ex)
					.log("sugestao-adaptacao-proposta não aplicada; job fora do estado de origem esperado (reentrega ou evento fora de ordem)");
				return;
			}

			if (aplicada == null) {
				log.atWarn()
					.addKeyValue("resultado_id", resultadoId)
					.log("sugestão descartada: origem inválida ou tentativa já realizada");
				return;
			}

			var original = aplicada.desfechoOriginal();
			if (original != null) {
				if (original.avancouDeGerandoRegra()) {
					this.emissores.emitir(jobId, EventoSse.de("estado",
							EventoEstadoDto.transicao(jobId, JobStatus.GERANDO_REGRA, JobStatus.SIMULANDO, null)));
				}
				UUID simulacaoId = original.simulacaoId();
				if (simulacaoId != null) {
					this.emissores.emitir(jobId, EventoSse.de("resultado",
							new EventoResultadoDto(jobId, simulacaoId, "sucesso", "inviavel")));
				}
				this.emissores.emitir(jobId, EventoSse.de("estado", EventoEstadoDto.transicao(jobId, original.origem(),
						JobStatus.SIMULACAO_INVIAVEL, DesfechoDaSimulacao.INVIAVEL.razaoLocalizada())));
			}

			this.emissores.emitir(jobId, EventoSse.de("estado",
					EventoEstadoDto.transicao(jobId, aplicada.origem(), JobStatus.GERANDO_REGRA, null)));
			log.atDebug().addKeyValue("regra_id", aplicada.versao().id()).log("sugestao-adaptacao-proposta aplicada");
		}
	}

}
