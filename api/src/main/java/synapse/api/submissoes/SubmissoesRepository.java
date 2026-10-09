package synapse.api.submissoes;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
class SubmissoesRepository {

	private final JdbcTemplate jdbc;

	SubmissoesRepository(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	UUID inserirTexto(UUID usuarioId, String texto, Instant agora) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, transcricao, criado_em)
				VALUES (?, 'texto', ?, ?) RETURNING id
				""", UUID.class, usuarioId, texto, Timestamp.from(agora)));
	}

	UUID inserirVoz(UUID usuarioId, AudioSubmissao audio, Instant agora) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO submissoes (usuario_id, tipo, binario, formato, criado_em)
				VALUES (?, 'voz', ?, ?, ?) RETURNING id
				""", UUID.class, usuarioId, audio.bytes(), audio.formato(), Timestamp.from(agora)));
	}

	void inserirTrabalho(UUID jobId, UUID submissaoId, Instant agora) {
		this.jdbc.update(
				"""
						INSERT INTO trabalhos_transcricao (job_id, submissao_id, finalidade, estado, tentativas, criado_em, atualizado_em)
						VALUES (?, ?, 'entrada_inicial', 'pendente', 0, ?, ?)
						""",
				jobId, submissaoId, Timestamp.from(agora), Timestamp.from(agora));
	}

	/**
	 * Reserva o trabalho elegível mais antigo e devolve a lista vazia quando não há
	 * nenhum. {@code SKIP LOCKED} faz outro processador pular a linha já travada em vez
	 * de esperar por ela, e a reserva vencida volta a ser elegível para que uma instância
	 * que caiu no meio da chamada não deixe o job preso. A finalidade {@code correcao}
	 * fica de fora até a T-238.
	 * <p>
	 * É uma instrução só, e portanto a transação curta da reserva: quem chama está em
	 * autocommit, e nada da chamada ao provedor acontece com esta linha travada.
	 */
	List<TrabalhoReservado> reservarTrabalho(Instant agora, Duration prazo) {
		return this.jdbc.query("""
				WITH alvo AS (
				    SELECT id, estado FROM trabalhos_transcricao
				    WHERE finalidade = 'entrada_inicial'
				      AND (estado = 'pendente' OR (estado = 'em_andamento' AND reservado_ate < ?))
				    ORDER BY criado_em, id
				    LIMIT 1
				    FOR UPDATE SKIP LOCKED
				)
				UPDATE trabalhos_transcricao t
				SET estado = 'em_andamento', tentativas = t.tentativas + 1, reservado_ate = ?, atualizado_em = ?
				FROM alvo WHERE t.id = alvo.id
				RETURNING t.id, t.job_id, t.submissao_id, t.tentativas, t.criado_em, alvo.estado AS estado_anterior
				""",
				(rs, numero) -> new TrabalhoReservado(Objects.requireNonNull(rs.getObject("id", UUID.class)),
						Objects.requireNonNull(rs.getObject("job_id", UUID.class)),
						Objects.requireNonNull(rs.getObject("submissao_id", UUID.class)), rs.getInt("tentativas"),
						Objects.requireNonNull(rs.getTimestamp("criado_em")).toInstant(),
						"em_andamento".equals(rs.getString("estado_anterior"))),
				Timestamp.from(agora), Timestamp.from(agora.plus(prazo)), Timestamp.from(agora));
	}

	/**
	 * Lê o áudio fora de qualquer transação: a conexão volta ao pool antes da chamada.
	 */
	List<AudioGravado> lerAudio(UUID submissaoId) {
		return this.jdbc.query("SELECT binario, formato FROM submissoes WHERE id = ?",
				(rs, numero) -> new AudioGravado(Objects.requireNonNull(rs.getBytes("binario")),
						Objects.requireNonNull(rs.getString("formato"))),
				submissaoId);
	}

	/**
	 * Retoma a reserva na transação final e devolve false quando ela não é mais nossa. A
	 * contagem de tentativas é a cerca: se outra instância reservou o mesmo trabalho
	 * depois do vencimento, o número mudou e este resultado é descartado sem gravar nada.
	 */
	boolean reservaAindaENossa(UUID trabalhoId, int tentativas) {
		return !this.jdbc.queryForList(
				"SELECT 1 FROM trabalhos_transcricao WHERE id = ? AND estado = 'em_andamento' AND tentativas = ? FOR UPDATE",
				trabalhoId, tentativas)
			.isEmpty();
	}

	void gravarTranscricao(UUID submissaoId, String texto, Instant agora) {
		this.jdbc.update("UPDATE submissoes SET transcricao = ?, transcrito_em = ? WHERE id = ?", texto,
				Timestamp.from(agora), submissaoId);
	}

	void encerrarTrabalho(UUID trabalhoId, String estado, Instant agora) {
		this.jdbc.update(
				"UPDATE trabalhos_transcricao SET estado = ?, reservado_ate = NULL, atualizado_em = ? WHERE id = ?",
				estado, Timestamp.from(agora), trabalhoId);
	}

	/**
	 * @param recuperado a reserva venceu e foi retomada, em vez de o trabalho estar
	 * pendente; é a reentrada que não conta espera nem conclusão nova
	 */
	record TrabalhoReservado(UUID id, UUID jobId, UUID submissaoId, int tentativas, Instant criadoEm,
			boolean recuperado) {
	}

	/** Classe, e não record: um record com componente de array é recusado na revisão. */
	static final class AudioGravado {

		private final byte[] bytes;

		private final String formato;

		private AudioGravado(byte[] bytes, String formato) {
			this.bytes = bytes;
			this.formato = formato;
		}

		byte[] bytes() {
			return this.bytes;
		}

		String formato() {
			return this.formato;
		}

	}

}
