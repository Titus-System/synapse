package synapse.api.core.outbox;

import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.springframework.amqp.AmqpException;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageBuilder;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.core.ReturnedMessage;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.logging.CorrelationContext;

/**
 * Um ciclo do poller do outbox: publica os eventos pendentes em ordem e marca como
 * publicado só o que o broker confirmou.
 */
@Component
class PublicadorOutbox {

	static final int LOTE = 50;

	static final Duration TIMEOUT_CONFIRMACAO = Duration.ofSeconds(5);

	private static final Logger log = LoggerFactory.getLogger(PublicadorOutbox.class);

	private final JdbcTemplate jdbc;

	private final RabbitTemplate rabbit;

	private final CorrelationContext correlacao;

	PublicadorOutbox(JdbcTemplate jdbc, RabbitTemplate rabbit, CorrelationContext correlacao) {
		this.jdbc = jdbc;
		this.rabbit = rabbit;
		this.correlacao = correlacao;
	}

	/**
	 * As linhas do lote ficam travadas até o fim da transação: um ciclo concorrente as
	 * pula ({@code SKIP LOCKED}) em vez de publicá-las de novo. A primeira falha encerra
	 * o ciclo, para que um evento posterior nunca passe à frente de um anterior.
	 */
	@Transactional
	void publicarPendentes() {
		List<Pendente> pendentes = this.jdbc.query("""
				SELECT id, job_id, tipo, payload::text AS payload
				FROM outbox_events
				WHERE publicado_em IS NULL
				ORDER BY criado_em, id
				LIMIT ?
				FOR UPDATE SKIP LOCKED
				""", (rs, linha) -> new Pendente(rs.getObject("id", UUID.class), rs.getObject("job_id", UUID.class),
				rs.getString("tipo"), rs.getString("payload")), LOTE);
		for (Pendente evento : pendentes) {
			try (var escopo = this.correlacao.abrir(evento.jobId().toString(), null)) {
				if (!publicar(evento)) {
					return;
				}
			}
		}
	}

	private boolean publicar(Pendente evento) {
		try {
			enviarComConfirmacao(evento);
		}
		catch (AmqpException | ExecutionException | TimeoutException ex) {
			registrarFalha(evento, ex);
			return false;
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
			registrarFalha(evento, ex);
			return false;
		}
		this.jdbc.update("""
				UPDATE outbox_events SET publicado_em = ?, tentativas = tentativas + 1
				WHERE id = ? AND publicado_em IS NULL
				""", Timestamp.from(Instant.now()), evento.id());
		log.atInfo()
			.addKeyValue("evento_id", evento.id())
			.addKeyValue("tipo_mensagem", evento.tipo())
			.log("evento do outbox publicado");
		return true;
	}

	/**
	 * Sem {@code mandatory}, uma mensagem sem fila de destino recebe {@code ack} e some;
	 * por isso a devolução também conta como falha.
	 */
	private void enviarComConfirmacao(Pendente evento)
			throws InterruptedException, ExecutionException, TimeoutException {
		Message mensagem = MessageBuilder.withBody(evento.payload().getBytes(StandardCharsets.UTF_8))
			.setContentType(MessageProperties.CONTENT_TYPE_JSON)
			.setContentEncoding("utf-8")
			.setDeliveryMode(MessageDeliveryMode.PERSISTENT)
			.setMessageId(evento.id().toString())
			.setCorrelationId(evento.jobId().toString())
			.setType(evento.tipo())
			.build();
		CorrelationData confirmacao = new CorrelationData(evento.id().toString());
		this.rabbit.send("", evento.tipo(), mensagem, confirmacao);
		CorrelationData.Confirm confirm = confirmacao.getFuture()
			.get(TIMEOUT_CONFIRMACAO.toMillis(), TimeUnit.MILLISECONDS);
		if (!confirm.ack()) {
			throw new AmqpException("broker recusou a mensagem: " + confirm.reason());
		}
		ReturnedMessage devolvida = confirmacao.getReturned();
		if (devolvida != null) {
			// Só código e texto de resposta: a mensagem devolvida carrega o payload.
			throw new AmqpException(
					"broker devolveu a mensagem: %d %s".formatted(devolvida.getReplyCode(), devolvida.getReplyText()));
		}
	}

	private void registrarFalha(Pendente evento, Exception causa) {
		Integer tentativas = Objects.requireNonNull(this.jdbc.queryForObject("""
				UPDATE outbox_events SET tentativas = tentativas + 1 WHERE id = ? RETURNING tentativas
				""", Integer.class, evento.id()));
		log.atWarn()
			.addKeyValue("evento_id", evento.id())
			.addKeyValue("tipo_mensagem", evento.tipo())
			.addKeyValue("tentativas", tentativas)
			.setCause(causa)
			.log("publicação de evento do outbox falhou; nova tentativa no próximo ciclo");
	}

	private record Pendente(UUID id, UUID jobId, String tipo, String payload) {
	}

}
