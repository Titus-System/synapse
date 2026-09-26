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

/**
 * Consome {@code sugestao-adaptacao-proposta}: grava a alternativa como versão nova da
 * regra e reabre o ciclo de geração. Nunca lança - toda entrada inválida ou fora de ordem
 * vira descarte com log {@code WARN}, porque uma exceção aqui viraria requeue infinito.
 *
 * <p>
 * A validação fica aqui, e não na desserialização, pelo mesmo motivo dos demais
 * consumidores: o payload vem da fila e nada nele é garantido em runtime. O conteúdo da
 * representação já foi validado contra o schema pelo publicador; o que se confere aqui é
 * a presença do que a gravação exige.
 */
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
		RepresentacaoRegraDto representacao = evento.representacao();
		if (jobId == null || regraOrigemId == null || representacao == null || representacao.nucleo() == null
				|| representacao.especificacoes() == null) {
			log.atWarn().log("sugestao-adaptacao-proposta incompleta; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			SugestaoAplicada aplicada;
			try {
				aplicada = this.servico.aplicar(jobId, regraOrigemId, representacao);
			}
			catch (TransicaoDeStatusInvalidaException ex) {
				log.atWarn()
					.setCause(ex)
					.log("sugestao-adaptacao-proposta não aplicada; job fora do estado de origem esperado (reentrega ou evento fora de ordem)");
				return;
			}

			this.emissores.emitir(jobId, EventoSse.de("estado",
					EventoEstadoDto.transicao(jobId, aplicada.origem(), JobStatus.GERANDO_REGRA, null)));
			log.atDebug().addKeyValue("regra_id", aplicada.versao().id()).log("sugestao-adaptacao-proposta aplicada");
		}
	}

}
