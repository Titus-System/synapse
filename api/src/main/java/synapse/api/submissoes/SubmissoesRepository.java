package synapse.api.submissoes;

import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
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

	void inserirTrabalho(UUID jobId, UUID submissaoId, FinalidadeTrabalho finalidade, Instant agora) {
		this.jdbc.update(
				"""
						INSERT INTO trabalhos_transcricao (job_id, submissao_id, finalidade, estado, tentativas, criado_em, atualizado_em)
						VALUES (?, ?, ?, 'pendente', 0, ?, ?)
						""",
				jobId, submissaoId, finalidade.paraColuna(), Timestamp.from(agora), Timestamp.from(agora));
	}

	/**
	 * Reserva o trabalho elegível mais antigo e devolve a lista vazia quando não há
	 * nenhum. {@code SKIP LOCKED} faz outro processador pular a linha já travada em vez
	 * de esperar por ela, e a reserva vencida volta a ser elegível para que uma instância
	 * que caiu no meio da chamada não deixe o job preso.
	 * <p>
	 * É uma instrução só, e portanto a transação curta da reserva: quem chama está em
	 * autocommit, e nada da chamada ao provedor acontece com esta linha travada.
	 */
	List<TrabalhoReservado> reservarTrabalho(Instant agora, Duration prazo, int limite) {
		return this.jdbc.query(
				"""
						WITH alvo AS (
						    SELECT id, estado, tentativas FROM trabalhos_transcricao
						    WHERE (estado = 'pendente' AND (proxima_tentativa_em IS NULL OR proxima_tentativa_em <= ?))
						       OR (estado = 'em_andamento' AND reservado_ate <= ?)
						    ORDER BY criado_em, id
						    LIMIT 1
						    FOR UPDATE SKIP LOCKED
						)
						UPDATE trabalhos_transcricao t
						SET estado = 'em_andamento', tentativas = CASE WHEN t.tentativas >= ? THEN t.tentativas ELSE t.tentativas + 1 END,
						    reservado_ate = ?, atualizado_em = ?
						FROM alvo WHERE t.id = alvo.id
						RETURNING t.id, t.job_id, t.submissao_id, t.finalidade, t.tentativas, t.criado_em, t.resposta_invalida,
						    t.reservado_ate, alvo.estado AS estado_anterior, alvo.tentativas AS tentativas_anteriores
						""",
				(rs, numero) -> new TrabalhoReservado(Objects.requireNonNull(rs.getObject("id", UUID.class)),
						Objects.requireNonNull(rs.getObject("job_id", UUID.class)),
						Objects.requireNonNull(rs.getObject("submissao_id", UUID.class)),
						FinalidadeTrabalho.deColuna(Objects.requireNonNull(rs.getString("finalidade"))),
						rs.getInt("tentativas"), Objects.requireNonNull(rs.getTimestamp("criado_em")).toInstant(),
						"em_andamento".equals(rs.getString("estado_anterior")), rs.getBoolean("resposta_invalida"),
						rs.getInt("tentativas_anteriores") >= limite,
						Objects.requireNonNull(rs.getTimestamp("reservado_ate")).toInstant()),
				Timestamp.from(agora), Timestamp.from(agora), limite, Timestamp.from(agora.plus(prazo)),
				Timestamp.from(agora));
	}

	void reagendar(UUID trabalhoId, Instant agora, Instant proxima, boolean respostaInvalida) {
		this.jdbc.update("""
				UPDATE trabalhos_transcricao SET estado = 'pendente', reservado_ate = NULL,
				    proxima_tentativa_em = ?, resposta_invalida = resposta_invalida OR ?, atualizado_em = ?
				WHERE id = ?
				""", Timestamp.from(proxima), respostaInvalida, Timestamp.from(agora), trabalhoId);
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
	 * tentativa e o prazo identificam a reserva, inclusive quando o limite já esgotou. Um
	 * resultado de uma reserva anterior não pode sobrescrever a recuperação.
	 */
	boolean reservaAindaENossa(UUID trabalhoId, int tentativas, Instant reservadoAte) {
		return !this.jdbc.queryForList(
				"SELECT 1 FROM trabalhos_transcricao WHERE id = ? AND estado = 'em_andamento' AND tentativas = ? AND reservado_ate = ? FOR UPDATE",
				trabalhoId, tentativas, Timestamp.from(reservadoAte))
			.isEmpty();
	}

	void gravarTranscricao(UUID submissaoId, String texto, Instant agora) {
		this.jdbc.update("UPDATE submissoes SET transcricao = ?, transcrito_em = ? WHERE id = ?", texto,
				Timestamp.from(agora), submissaoId);
	}

	void encerrarTrabalho(UUID trabalhoId, String estado, Instant agora) {
		this.jdbc.update(
				"UPDATE trabalhos_transcricao SET estado = ?, reservado_ate = NULL, proxima_tentativa_em = NULL, atualizado_em = ? WHERE id = ?",
				estado, Timestamp.from(agora), trabalhoId);
	}

	/**
	 * @param recuperado a reserva venceu e foi retomada, em vez de o trabalho estar
	 * pendente; é a reentrada que não conta espera nem conclusão nova
	 */
	record TrabalhoReservado(UUID id, UUID jobId, UUID submissaoId, FinalidadeTrabalho finalidade, int tentativas,
			Instant criadoEm, boolean recuperado, boolean respostaInvalida, boolean limiteEsgotado,
			Instant reservadoAte) {
	}

	enum FinalidadeTrabalho {

		ENTRADA_INICIAL, CORRECAO;

		String paraColuna() {
			return name().toLowerCase(Locale.ROOT);
		}

		static FinalidadeTrabalho deColuna(String valor) {
			return valueOf(valor.toUpperCase(Locale.ROOT));
		}

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
