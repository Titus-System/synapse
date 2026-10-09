package synapse.api.submissoes;

import java.sql.Timestamp;
import java.time.Instant;
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

}
