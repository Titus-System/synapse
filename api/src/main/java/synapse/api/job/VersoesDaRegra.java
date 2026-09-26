package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * Resolve a versão de {@code regras} de um job: reaproveita a linha de mesmo hash ou
 * insere a próxima. Único lugar que escreve na tabela, para que a regra de deduplicação e
 * a numeração da versão não se repitam por caminho de entrada - hoje a confirmação do
 * usuário e a sugestão de adaptação, que só diferem em {@code origem} e na versão de que
 * derivam.
 *
 * <p>
 * A deduplicação por {@code (job_id, hash)} é o que faz reenviar a mesma representação
 * não criar versão nova: é ela que sustenta o índice único da migration {@code 006} e o
 * caminho em que o usuário confirma sem ter editado nada.
 */
@Component
class VersoesDaRegra {

	private final JdbcTemplate jdbc;

	private final JsonMapper json = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	VersoesDaRegra(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	VersaoRegra resolver(UUID jobId, RepresentacaoRegraDto representacao, String hash, String origem,
			@Nullable UUID origemId, Timestamp timestamp, Instant agora) {
		List<VersaoRegra> existentes = this.jdbc.query("""
				SELECT id, versao, origem, criada_em FROM regras WHERE job_id = ? AND hash = ?
				""",
				(rs, linha) -> new VersaoRegra(Objects.requireNonNull(rs.getObject("id", UUID.class)),
						rs.getInt("versao"), Objects.requireNonNull(rs.getString("origem")),
						Objects.requireNonNull(rs.getTimestamp("criada_em")).toInstant()),
				jobId, hash);
		if (!existentes.isEmpty()) {
			return existentes.getFirst();
		}

		int novaVersao = proximaVersao(jobId);
		UUID id = Objects.requireNonNull(this.jdbc.queryForObject("""
				INSERT INTO regras (job_id, versao, origem, regra_origem_id, nucleo, especificacoes, hash, criada_em)
				VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?) RETURNING id
				""", UUID.class, jobId, novaVersao, origem, origemId,
				this.json.writeValueAsString(representacao.nucleo()),
				this.json.writeValueAsString(representacao.especificacoes()), hash, timestamp));
		return new VersaoRegra(id, novaVersao, origem, agora);
	}

	private int proximaVersao(UUID jobId) {
		Integer maior = this.jdbc.queryForObject("SELECT COALESCE(MAX(versao), 0) FROM regras WHERE job_id = ?",
				Integer.class, jobId);
		return ((maior != null) ? maior : 0) + 1;
	}

	record VersaoRegra(UUID id, int versao, String origem, Instant criadaEm) {
	}

}
