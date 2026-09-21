package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
class BuscarJobService {

	private final JdbcTemplate jdbc;

	private final JsonMapper json = new JsonMapper();

	BuscarJobService(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	JobDetalhadoDto buscar(UUID jobId) {
		try {
			return this.jdbc.queryForObject("""
					SELECT
					    j.id,
					    j.status,
					    s.tipo AS origem,
					    j.competencias,
					    j.orcamento,
					    j.criado_em,
					    j.iniciado_em,
					    j.finalizado_em,
					    j.submissao_id,
					    regras.regras,

					    sim.id AS simulacao_id,
					    sim.criado_em AS simulacao_criada_em,
					    sim.flag_baixa_rastreabilidade,

					    rs.status AS simulacao_status,
					    rs.veredito AS simulacao_veredito,
					    rs.totais AS simulacao_totais,
					    rs.assercoes AS simulacao_assercoes,
					    rs.decomposicao AS simulacao_decomposicao

					FROM jobs j
					JOIN submissoes s ON s.id = j.submissao_id
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
					LEFT JOIN LATERAL (
					    SELECT simulacao.*
					    FROM simulacoes simulacao
					    WHERE simulacao.job_id = j.id
					    ORDER BY simulacao.criado_em DESC, simulacao.id DESC
					    LIMIT 1
					) sim ON true
					LEFT JOIN resultados_simulacao rs ON rs.id = sim.resultado_id
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

				List<RegraCriadaDto> regras = regras(rs.getString("regras"));

				UUID simulacaoId = rs.getObject("simulacao_id", UUID.class);

				SimulacaoDto simulacao = null;

				if (simulacaoId != null) {
					Instant simulacaoCriadaEm = rs.getTimestamp("simulacao_criada_em").toInstant();
					boolean flagBaixaRastreabilidade = rs.getBoolean("flag_baixa_rastreabilidade");

					String simulacaoStatus = rs.getString("simulacao_status");
					String simulacaoVeredito = rs.getString("simulacao_veredito");

					ResultadoSimulacaoDto resultado = null;

					if (simulacaoStatus != null) {
						TotaisSimulacaoDto totais = rs.getString("simulacao_totais") != null
								? this.json.readValue(rs.getString("simulacao_totais"), TotaisSimulacaoDto.class)
								: null;

						List<ResultadoAssercaoDto> assercoes = this.json.readValue(rs.getString("simulacao_assercoes"),
								new TypeReference<List<ResultadoAssercaoDto>>() {
								});

						DecomposicaoResultadoDto decomposicao = rs.getString("simulacao_decomposicao") != null
								? this.json.readValue(rs.getString("simulacao_decomposicao"),
										DecomposicaoResultadoDto.class)
								: null;

						resultado = new ResultadoSimulacaoDto(totais, assercoes, decomposicao);
					}

					simulacao = new SimulacaoDto(simulacaoId, simulacaoCriadaEm, simulacaoStatus, simulacaoVeredito,
							flagBaixaRastreabilidade, resultado);
				}

				return new JobDetalhadoDto(id, status, origem, competencias, orcamento, criadoEm, iniciadoEm,
						finalizadoEm, submissaoId, regras, simulacao);
			}, jobId);
		}
		catch (EmptyResultDataAccessException ex) {
			throw new JobNaoEncontradoException(jobId);
		}
	}

	private List<RegraCriadaDto> regras(String regrasJson) {
		JsonNode raiz = this.json.readTree(regrasJson);
		List<RegraCriadaDto> regras = new ArrayList<>();
		for (JsonNode regra : raiz) {
			NucleoRegraDto nucleo = this.json.readValue(regra.path("nucleo").toString(), NucleoRegraDto.class);
			List<EspecificacaoRegraDto> especificacoes = this.json.readValue(regra.path("especificacoes").toString(),
					new TypeReference<List<EspecificacaoRegraDto>>() {
					});
			RepresentacaoRegraDto representacao = new RepresentacaoRegraDto(nucleo, especificacoes);
			regras.add(new RegraCriadaDto(UUID.fromString(regra.path("id").asString()), regra.path("versao").asInt(),
					regra.path("origem").asString(), representacao, Instant.parse(regra.path("criada_em").asString())));
		}
		return List.copyOf(regras);
	}

}
