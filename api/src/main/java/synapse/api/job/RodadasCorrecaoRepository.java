package synapse.api.job;

import java.sql.Timestamp;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
class RodadasCorrecaoRepository {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private final JdbcTemplate jdbc;

	private final ObjectMapper mapper;

	RodadasCorrecaoRepository(JdbcTemplate jdbc, ObjectMapper mapper) {
		this.jdbc = jdbc;
		this.mapper = mapper;
	}

	List<UUID> buscarPorRegra(UUID jobId, UUID regraId) {
		return this.jdbc.query(
				"SELECT id FROM rodadas_correcao WHERE job_id = ? AND regra_analisada_id = ? ORDER BY criada_em, id LIMIT 1",
				(rs, numero) -> Objects.requireNonNull(rs.getObject("id", UUID.class)), jobId, regraId);
	}

	List<UUID> buscarUltima(UUID jobId) {
		return this.jdbc.query(
				"SELECT id FROM rodadas_correcao WHERE job_id = ? ORDER BY criada_em DESC, id DESC LIMIT 1",
				(rs, numero) -> Objects.requireNonNull(rs.getObject("id", UUID.class)), jobId);
	}

	List<TentativaDeCorrecao> buscarPorSubmissao(UUID jobId, UUID submissaoId) {
		return this.jdbc.query("""
				SELECT id, regra_analisada_id, conflitos::text, estado, regra_resultante_id,
				       proposta_nao_aplicada::text FROM rodadas_correcao
				WHERE job_id = ? AND submissao_correcao_id = ?
				""",
				(rs, numero) -> new TentativaDeCorrecao(Objects.requireNonNull(rs.getObject("id", UUID.class)),
						Objects.requireNonNull(rs.getObject("regra_analisada_id", UUID.class)),
						JSON.readTree(rs.getString("conflitos")), Objects.requireNonNull(rs.getString("estado")),
						rs.getObject("regra_resultante_id", UUID.class), rs.getString("proposta_nao_aplicada") == null
								? null : JSON.readTree(rs.getString("proposta_nao_aplicada"))),
				jobId, submissaoId);
	}

	boolean regraPertenceAVersaoAtual(UUID jobId, UUID regraId) {
		return Boolean.TRUE.equals(this.jdbc.queryForObject("""
				SELECT EXISTS (SELECT 1 FROM regras r WHERE r.id = ? AND r.job_id = ?
				AND r.versao = (SELECT max(versao) FROM regras WHERE job_id = ?))
				""", Boolean.class, regraId, jobId, jobId));
	}

	UUID inserirPendente(UUID jobId, UUID regraId, JsonNode conflitos, @Nullable UUID anteriorId, Timestamp agora) {
		return Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO rodadas_correcao
				(job_id, regra_analisada_id, conflitos, estado, rodada_anterior_id, criada_em, atualizada_em)
				VALUES (?, ?, ?::jsonb, 'pendente', ?, ?, ?) RETURNING id
				""", UUID.class, jobId, regraId, this.mapper.writeValueAsString(conflitos), anteriorId, agora, agora));
	}

	void fecharReextracao(UUID rodadaId, Timestamp agora) {
		this.jdbc.update(
				"UPDATE rodadas_correcao SET estado = 'reextracao_falhou', atualizada_em = ? WHERE id = ? AND estado = 'em_reextracao'",
				agora, rodadaId);
	}

	void fecharProposta(UUID jobId, UUID rodadaId, UUID submissaoId, JsonNode corpo, Timestamp agora) {
		int alteradas = this.jdbc.update("""
				UPDATE rodadas_correcao SET estado = 'reextracao_falhou', proposta_nao_aplicada = ?::jsonb,
				atualizada_em = ? WHERE id = ? AND job_id = ? AND submissao_correcao_id = ? AND estado = 'em_reextracao'
				""", corpo.toString(), agora, rodadaId, jobId, submissaoId);
		if (alteradas != 1)
			throw new IllegalStateException("Tentativa de correção não disponível");
	}

	record TentativaDeCorrecao(UUID id, UUID regraId, JsonNode conflitos, String estado, @Nullable UUID resultanteId,
			@Nullable JsonNode propostaNaoAplicada) {
	}

}
