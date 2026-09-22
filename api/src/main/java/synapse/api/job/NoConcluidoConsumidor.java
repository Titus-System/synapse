package synapse.api.job;

import java.util.UUID;

import tools.jackson.databind.JsonNode;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.messaging.RabbitTopologyConfig;

/**
 * Consome {@code no-concluido} e grava a trilha de auditoria (T-046): uma linha em
 * {@code trilhas_auditoria} por nó concluído e, no nó {@code geracao_codigo}, a linha em
 * {@code simulacoes} que amarra a versão da regra ao código executado. Deduplica por
 * {@code evento_id} (índice único em {@code trilhas_auditoria}), a chave de idempotência
 * que o próprio contrato prevê. Nunca lança em entrada inválida: vira descarte com log
 * {@code WARN}, porque uma exceção aqui viraria requeue infinito. Não loga
 * {@code conclusao} (`api/AGENTS.md`): nenhum conteúdo de prompt, código ou dataset entra
 * em log.
 */
@Component
class NoConcluidoConsumidor {

	private static final Logger log = LoggerFactory.getLogger(NoConcluidoConsumidor.class);

	private final NoConcluidoService servico;

	private final CorrelationContext correlacao;

	NoConcluidoConsumidor(NoConcluidoService servico, CorrelationContext correlacao) {
		this.servico = servico;
		this.correlacao = correlacao;
	}

	@RabbitListener(queues = RabbitTopologyConfig.NO_CONCLUIDO)
	void receber(NoConcluidoDto evento) {
		UUID jobId = evento.job_id();
		if (jobId == null) {
			log.atWarn().log("no-concluido sem job_id; evento descartado");
			return;
		}

		try (var escopo = this.correlacao.abrir(jobId.toString(), null)) {
			UUID eventoId = evento.evento_id();
			EtapaDoGrafo no = EtapaDoGrafo.deEvento(evento.no());
			if (eventoId == null || no == null || evento.concluido_em() == null || evento.conclusao() == null
					|| !temResumo(evento.conclusao())) {
				log.atWarn().addKeyValue("no", evento.no()).log("no-concluido inválido; evento descartado");
				return;
			}

			if (no == EtapaDoGrafo.CONFIRMACAO) {
				// ConfirmarParametrosService já grava essa linha na mesma transação da
				// confirmação; gravar de novo aqui duplicaria a trilha.
				log.atInfo().log("no-concluido do nó confirmacao descartado; trilha já gravada pela confirmação");
				return;
			}

			try {
				this.servico.aplicar(jobId, eventoId, no, evento);
			}
			catch (EmptyResultDataAccessException ex) {
				log.atWarn().setCause(ex).log("no-concluido de job desconhecido; evento descartado");
				return;
			}
			log.atDebug().addKeyValue("no", no.paraEvento()).log("no-concluido gravado na trilha");
		}
	}

	private static boolean temResumo(JsonNode conclusao) {
		JsonNode resumo = conclusao.path("resumo");
		return resumo.isString() && StringUtils.hasText(resumo.asString());
	}

}
