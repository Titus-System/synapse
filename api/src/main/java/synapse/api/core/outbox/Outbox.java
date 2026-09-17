package synapse.api.core.outbox;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.UUID;

import tools.jackson.databind.json.JsonMapper;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Grava um evento para publicação na mesma transação da operação de negócio que o
 * originou. A publicação no RabbitMQ acontece depois, pelo {@link PublicadorOutbox}.
 * Chame dentro do método transacional que grava o job ou o estado:
 *
 * <pre>{@code
 * UUID jobId = inserirJob(...);
 * outbox.registrar(jobId, EventoOutbox.REGRA_SUBMETIDA, new RegraSubmetidaDto(...));
 * }</pre>
 */
@Component
public class Outbox {

	private final JdbcTemplate jdbc;

	private final JsonMapper json = new JsonMapper();

	Outbox(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	/**
	 * {@code MANDATORY}: sem uma transação aberta pelo chamador, lança
	 * {@code IllegalTransactionStateException} em vez de gravar o evento sozinho, o que
	 * permitiria confirmar o evento sem a operação que o originou ou o contrário.
	 * @param payload corpo publicado, serializado como JSON; carrega referências, nunca o
	 * conteúdo de um artefato
	 */
	@Transactional(propagation = Propagation.MANDATORY)
	public void registrar(UUID jobId, EventoOutbox evento, Object payload) {
		this.jdbc.update("""
				INSERT INTO outbox_events (job_id, tipo, payload, criado_em)
				VALUES (?, ?, ?::jsonb, ?)
				""", jobId, evento.tipo(), this.json.writeValueAsString(payload), Timestamp.from(Instant.now()));
	}

}
