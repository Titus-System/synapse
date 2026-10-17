package synapse.api.job;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import synapse.api.job.JobsDeSubmissoes.Correcao;
import synapse.api.job.JobsDeSubmissoes.Rodada;

@Repository
class RodadasRepository {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private static final String CONSULTA = """
			SELECT r.id, r.rodada_anterior_id, r.regra_analisada_id, r.conflitos::text, r.estado,
			       r.regra_resultante_id, r.criada_em, s.id AS submissao_id, s.tipo, s.transcricao,
			       s.criado_em AS enviada_em
			FROM rodadas_correcao r LEFT JOIN submissoes s ON s.id = r.submissao_correcao_id
			""";

	private final JdbcTemplate jdbc;

	RodadasRepository(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	List<Rodada> listar(UUID jobId) {
		return this.jdbc.query(CONSULTA + " WHERE r.job_id = ? ORDER BY r.criada_em, r.id",
				(rs, numero) -> converter(rs), jobId);
	}

	List<Rodada> abertas(UUID jobId) {
		return this.jdbc.query(CONSULTA + " WHERE r.job_id = ? AND r.estado IN ('pendente', 'em_reextracao')",
				(rs, numero) -> converter(rs), jobId);
	}

	Rodada buscar(UUID id) {
		return Objects
			.requireNonNull(this.jdbc.queryForObject(CONSULTA + " WHERE r.id = ?", (rs, numero) -> converter(rs), id));
	}

	boolean jaAnalisada(UUID jobId, UUID regraId) {
		return Boolean.TRUE.equals(this.jdbc.queryForObject("""
				SELECT EXISTS (SELECT 1 FROM rodadas_correcao WHERE job_id = ? AND regra_analisada_id = ?)
				""", Boolean.class, jobId, regraId));
	}

	void receber(UUID rodadaId, UUID submissaoId, Instant agora) {
		int alteradas = this.jdbc.update("""
				UPDATE rodadas_correcao SET estado = ?, submissao_correcao_id = ?, atualizada_em = ?
				WHERE id = ? AND estado = 'pendente'
				""", EstadoRodada.EM_REEXTRACAO.paraColuna(), submissaoId, Timestamp.from(agora), rodadaId);
		if (alteradas != 1) {
			throw new IllegalStateException("A rodada não está mais pendente.");
		}
	}

	void corrigir(UUID jobId, UUID rodadaId, UUID regraAnalisadaId, UUID regraResultanteId, Instant agora) {
		int alteradas = this.jdbc.update("""
				UPDATE rodadas_correcao SET estado = 'corrigida', regra_resultante_id = ?, atualizada_em = ?
				WHERE id = ? AND job_id = ? AND regra_analisada_id = ? AND estado IN ('pendente', 'em_reextracao')
				AND EXISTS (SELECT 1 FROM regras WHERE id = ? AND job_id = ?)
				AND EXISTS (SELECT 1 FROM regras WHERE id = ? AND job_id = ?)
				""", regraResultanteId, Timestamp.from(agora), rodadaId, jobId, regraAnalisadaId, regraAnalisadaId,
				jobId, regraResultanteId, jobId);
		if (alteradas != 1) {
			throw new IllegalStateException("A rodada não corresponde à confirmação do job.");
		}
	}

	int abandonarAbertas(UUID jobId, Instant agora) {
		return this.jdbc.update("""
				UPDATE rodadas_correcao SET estado = ?, atualizada_em = ?
				WHERE job_id = ? AND estado IN ('pendente', 'em_reextracao')
				""", EstadoRodada.ABANDONADA.paraColuna(), Timestamp.from(agora), jobId);
	}

	private static Rodada converter(ResultSet rs) throws SQLException {
		Correcao correcao = rs.getObject("submissao_id") == null ? null
				: new Correcao(Objects.requireNonNull(rs.getString("tipo")), rs.getString("transcricao"),
						Objects.requireNonNull(rs.getTimestamp("enviada_em")).toInstant());
		return new Rodada(Objects.requireNonNull(rs.getObject("id", UUID.class)),
				rs.getObject("rodada_anterior_id", UUID.class),
				Objects.requireNonNull(rs.getObject("regra_analisada_id", UUID.class)),
				JSON.readTree(Objects.requireNonNull(rs.getString("conflitos"))), correcao,
				rs.getObject("regra_resultante_id", UUID.class),
				EstadoRodada.deColuna(Objects.requireNonNull(rs.getString("estado"))).paraColuna(),
				Objects.requireNonNull(rs.getTimestamp("criada_em")).toInstant());
	}

}
