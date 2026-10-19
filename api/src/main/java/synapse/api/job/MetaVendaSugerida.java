package synapse.api.job;

import java.math.BigDecimal;
import java.util.Set;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.messaging.RabbitTopologyConfig;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;

record SemSolucaoDto(@Nullable String motivo) {
}

record MetaVendaSugeridaDto(@Nullable UUID job_id, @Nullable UUID regra_id, @Nullable UUID resultado_id,
		@Nullable BigDecimal meta_venda, @Nullable SemSolucaoDto sem_solucao) {

	boolean valida() {
		if (this.job_id == null || this.regra_id == null) {
			return false;
		}
		if (this.sem_solucao != null) {
			String motivo = this.sem_solucao.motivo();
			return this.resultado_id == null && this.meta_venda == null && motivo != null
					&& Set.of("nao_monotonica", "intervalo_esgotado", "falha_execucao").contains(motivo);
		}
		return this.resultado_id != null && this.meta_venda != null && this.meta_venda.signum() > 0;
	}

}

/** Forma pública: números são lidos do artefato do worker, nunca do evento. */
@JsonInclude(JsonInclude.Include.NON_NULL)
record MetaSugeridaDto(@Nullable BigDecimal meta_venda, @Nullable BigDecimal total_simulado,
		@Nullable BigDecimal orcamento, @Nullable SemSolucaoDto sem_solucao) {
}

@Component
class MetaVendaSugeridaConsumidor {

	private static final Logger log = LoggerFactory.getLogger(MetaVendaSugeridaConsumidor.class);

	private final JobEventosService servico;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	private final AppMetrics metricas;

	MetaVendaSugeridaConsumidor(JobEventosService servico, EmissoresSse emissores, CorrelationContext correlacao,
			AppMetrics metricas) {
		this.servico = servico;
		this.emissores = emissores;
		this.correlacao = correlacao;
		this.metricas = metricas;
	}

	@RabbitListener(queues = RabbitTopologyConfig.META_VENDA_SUGERIDA)
	void receber(MetaVendaSugeridaDto evento) {
		try (var escopo = this.correlacao.abrir(evento.job_id() == null ? null : evento.job_id().toString(), null)) {
			if (!evento.valida()) {
				this.metricas.metaVendaSugeridaConsumida("invalida").increment();
				log.atWarn().log("meta-venda-sugerida inválida; evento descartado");
				return;
			}
			boolean aplicada;
			try {
				aplicada = this.servico.registrarMetaSugerida(evento);
			}
			catch (org.springframework.dao.DataAccessException ex) {
				this.metricas.metaVendaSugeridaConsumida("falha").increment();
				log.atWarn().log("falha de persistência da meta sugerida; entrega será repetida");
				throw ex;
			}
			String resultado = aplicada ? "registrada" : "descartada";
			this.metricas.metaVendaSugeridaConsumida(resultado).increment();
			log.atInfo().addKeyValue("resultado", resultado).log("meta-venda-sugerida consumida");
			if (aplicada) {
				// O proxy transacional já confirmou a gravação antes de anunciar no SSE.
				UUID jobId = java.util.Objects.requireNonNull(evento.job_id());
				this.emissores.emitir(jobId, EventoSse.de("etapa", new EventoEtapaDto(jobId, "sugestao_adaptacao",
						evento.sem_solucao() == null ? "meta_sugerida" : "sem_solucao")));
			}
		}
	}

}
