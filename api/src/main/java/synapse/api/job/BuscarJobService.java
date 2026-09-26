package synapse.api.job;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Service
class BuscarJobService {

	private final JdbcTemplate jdbc;

	private final JsonMapper json = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	BuscarJobService(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
	JobDetalhadoDto buscar(UUID jobId) {
		try {
			JobDetalhadoDto job = this.jdbc.queryForObject("""
					SELECT
					    j.id,
					    j.status,
					    CASE WHEN j.job_origem_id IS NOT NULL THEN 'reprocessamento' ELSE s.tipo END AS origem,
					    j.competencias,
					    j.orcamento,
					    j.criado_em,
					    j.iniciado_em,
					    j.finalizado_em,
					    j.submissao_id,
					    j.job_origem_id,
					    regras.regras

					FROM jobs j
					LEFT JOIN submissoes s ON s.id = j.submissao_id
					JOIN LATERAL (
					    SELECT jsonb_agg(
					        jsonb_build_object(
					            'id', r.id,
					            'versao', r.versao,
					            'origem', r.origem,
					            'nucleo', r.nucleo,
					            'especificacoes', r.especificacoes,
					            'criada_em', r.criada_em
					        ) ORDER BY r.versao
					    ) AS regras
					    FROM regras r
					    WHERE r.job_id = j.id
					) regras ON regras.regras IS NOT NULL
					WHERE j.id = ?
					""", (rs, rowNum) -> {
				UUID id = rs.getObject("id", UUID.class);
				String status = rs.getString("status");
				String origem = rs.getString("origem");
				List<String> competencias = List.of((String[]) rs.getArray("competencias").getArray());
				BigDecimal orcamento = rs.getBigDecimal("orcamento");
				Instant criadoEm = rs.getTimestamp("criado_em").toInstant();
				Instant iniciadoEm = rs.getTimestamp("iniciado_em") != null ? rs.getTimestamp("iniciado_em").toInstant()
						: null;
				Instant finalizadoEm = rs.getTimestamp("finalizado_em") != null
						? rs.getTimestamp("finalizado_em").toInstant() : null;
				UUID submissaoId = rs.getObject("submissao_id", UUID.class);
				UUID jobOrigemId = rs.getObject("job_origem_id", UUID.class);

				List<RegraCriadaDto> regras = regras(rs.getString("regras"));

				return new JobDetalhadoDto(id, status, origem, competencias, orcamento, criadoEm, iniciadoEm,
						finalizadoEm, submissaoId, jobOrigemId, regras, null, List.of());
			}, jobId);
			List<SimulacaoDto> simulacoes = simulacoes(jobId);
			SimulacaoDto simulacao = simulacoes.isEmpty() ? null : simulacoes.getLast();
			return new JobDetalhadoDto(job.id(), job.status(), job.origem(), job.competencias(), job.orcamento(),
					job.criado_em(), job.iniciado_em(), job.finalizado_em(), job.submissao_id(), job.job_origem_id(),
					job.regras(), simulacao, simulacoes);
		}
		catch (EmptyResultDataAccessException ex) {
			throw new JobNaoEncontradoException(jobId);
		}
	}

	private List<SimulacaoDto> simulacoes(UUID jobId) {
		return this.jdbc.query("""
				SELECT s.id, s.regra_id, s.criado_em, s.flag_baixa_rastreabilidade,
				       r.status, r.veredito, r.totais, r.assercoes, r.decomposicao
				FROM simulacoes s
				LEFT JOIN resultados_simulacao r ON r.id = s.resultado_id
				WHERE s.job_id = ? ORDER BY s.criado_em, s.id
				""", (rs, numero) -> simulacao(rs), jobId);
	}

	private SimulacaoDto simulacao(ResultSet rs) throws SQLException {
		ResultadoSimulacaoDto resultado = null;
		if (rs.getString("status") != null) {
			TotaisSimulacaoDto totais = rs.getString("totais") == null ? null
					: this.json.readValue(rs.getString("totais"), TotaisSimulacaoDto.class);
			List<ResultadoAssercaoDto> assercoes = this.json.readValue(rs.getString("assercoes"),
					new TypeReference<List<ResultadoAssercaoDto>>() {
					});
			DecomposicaoResultadoDto decomposicao = rs.getString("decomposicao") == null ? null
					: this.json.readValue(rs.getString("decomposicao"), DecomposicaoResultadoDto.class);
			resultado = new ResultadoSimulacaoDto(totais, assercoes, decomposicao);
		}
		return new SimulacaoDto(rs.getObject("id", UUID.class), rs.getObject("regra_id", UUID.class),
				rs.getTimestamp("criado_em").toInstant(), rs.getString("status"), rs.getString("veredito"),
				rs.getBoolean("flag_baixa_rastreabilidade"), resultado);
	}

	private List<RegraCriadaDto> regras(String regrasJson) {
		JsonNode raiz = this.json.readTree(regrasJson);
		List<RegraCriadaDto> regras = new ArrayList<>();
		for (JsonNode regra : raiz) {
			NucleoRegraDto nucleo = this.json.readValue(regra.path("nucleo").toString(), NucleoRegraDto.class);
			List<JsonNode> especificacoes = regra.path("especificacoes").valueStream().toList();
			RepresentacaoRegraDto representacao = new RepresentacaoRegraDto(nucleo, especificacoes);
			regras.add(new RegraCriadaDto(UUID.fromString(regra.path("id").asString()), regra.path("versao").asInt(),
					regra.path("origem").asString(), representacao, Instant.parse(regra.path("criada_em").asString())));
		}
		return List.copyOf(regras);
	}

}
