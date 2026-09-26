package synapse.api.job;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.SqlArrayValue;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;
import synapse.api.job.VersoesDaRegra.VersaoRegra;

/**
 * Confirma ou corrige a representação da regra: grava uma versão nova (imutável), publica
 * {@code parametros-confirmados} pelo outbox, transiciona o job para
 * {@code gerando_regra} e registra a edição na trilha. Tudo na mesma transação; a
 * imutabilidade da versão anterior é garantida pelo banco (a api só tem {@code INSERT} em
 * {@code regras}), não por convenção.
 */
@Service
class ConfirmarParametrosService {

	private final JdbcTemplate jdbc;

	private final MaquinaDeEstadosDoJob maquina;

	private final Outbox outbox;

	private final VersoesDaRegra versoes;

	private final JsonMapper json = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	ConfirmarParametrosService(JdbcTemplate jdbc, MaquinaDeEstadosDoJob maquina, Outbox outbox,
			VersoesDaRegra versoes) {
		this.jdbc = jdbc;
		this.maquina = maquina;
		this.outbox = outbox;
		this.versoes = versoes;
	}

	@Transactional
	JobCriadoDto confirmar(UUID jobId, ConfirmarParametrosRequisicao requisicao) {
		DadosDoJob dados = carregarJob(jobId);
		this.maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "usuario", null);

		VersaoAnterior anterior = ultimaVersao(jobId);
		RepresentacaoRegraDto representacao = requisicao.representacao();
		String hash = HashDaRegra.calcular(representacao);
		boolean editado = anterior != null && !hash.equals(anterior.hash());

		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		Timestamp timestamp = Timestamp.from(agora);
		VersaoRegra versao = this.versoes.resolver(jobId, representacao, hash, "confirmacao_usuario",
				(anterior != null) ? anterior.id() : null, timestamp, agora);

		BigDecimal orcamento = resolverOrcamento(jobId, requisicao, dados.orcamento());
		List<String> competencias = resolverCompetencias(jobId, requisicao);

		this.outbox.registrar(jobId, EventoOutbox.PARAMETROS_CONFIRMADOS,
				new ParametrosConfirmadosDto(jobId, versao.id()));
		registrarTrilha(jobId, versao.id(), editado, representacao, anterior, timestamp);

		RegraCriadaDto regra = new RegraCriadaDto(versao.id(), versao.versao(), versao.origem(), representacao,
				versao.criadaEm());
		return new JobCriadoDto(jobId, JobStatus.GERANDO_REGRA.paraColuna(), dados.origem(), competencias, orcamento,
				dados.criadoEm(), dados.submissaoId(), dados.jobOrigemId(), regra);
	}

	private DadosDoJob carregarJob(UUID jobId) {
		try {
			return Objects.requireNonNull(this.jdbc.queryForObject("""
					SELECT CASE WHEN j.job_origem_id IS NOT NULL THEN 'reprocessamento' ELSE s.tipo END AS origem,
					       j.orcamento, j.criado_em, j.submissao_id, j.job_origem_id
					FROM jobs j LEFT JOIN submissoes s ON s.id = j.submissao_id
					WHERE j.id = ?
					""",
					(rs, linha) -> new DadosDoJob(Objects.requireNonNull(rs.getString("origem")),
							Objects.requireNonNull(rs.getBigDecimal("orcamento")),
							Objects.requireNonNull(rs.getTimestamp("criado_em")).toInstant(),
							rs.getObject("submissao_id", UUID.class), rs.getObject("job_origem_id", UUID.class)),
					jobId));
		}
		catch (EmptyResultDataAccessException ex) {
			throw new JobNaoEncontradoException(jobId);
		}
	}

	private @Nullable VersaoAnterior ultimaVersao(UUID jobId) {
		List<VersaoAnterior> versoes = this.jdbc.query(
				"""
						SELECT id, versao, hash, nucleo, especificacoes FROM regras WHERE job_id = ? ORDER BY versao DESC LIMIT 1
						""",
				(rs, linha) -> new VersaoAnterior(Objects.requireNonNull(rs.getObject("id", UUID.class)),
						rs.getInt("versao"), Objects.requireNonNull(rs.getString("hash")),
						this.json.readValue(Objects.requireNonNull(rs.getString("nucleo")), NucleoRegraDto.class),
						this.json.readTree(Objects.requireNonNull(rs.getString("especificacoes")))
							.valueStream()
							.toList()),
				jobId);
		return versoes.isEmpty() ? null : versoes.getFirst();
	}

	private BigDecimal resolverOrcamento(UUID jobId, ConfirmarParametrosRequisicao requisicao, BigDecimal atual) {
		BigDecimal novo = requisicao.orcamento();
		if (novo == null) {
			return atual;
		}
		this.jdbc.update("UPDATE jobs SET orcamento = ? WHERE id = ?", novo, jobId);
		return novo;
	}

	private List<String> resolverCompetencias(UUID jobId, ConfirmarParametrosRequisicao requisicao) {
		List<String> novas = requisicao.competencias();
		if (novas != null) {
			this.jdbc.update("UPDATE jobs SET competencias = ? WHERE id = ?",
					new SqlArrayValue("text", novas.toArray()), jobId);
			return novas;
		}
		return this.jdbc.queryForList("SELECT unnest(competencias) FROM jobs WHERE id = ?", String.class, jobId);
	}

	private void registrarTrilha(UUID jobId, UUID regraId, boolean editado, RepresentacaoRegraDto atual,
			@Nullable VersaoAnterior anterior, Timestamp timestamp) {
		List<String> corrigidos = (anterior != null && editado) ? camposCorrigidos(atual.nucleo(), anterior.nucleo())
				: new ArrayList<>();
		if (anterior != null && editado) {
			corrigidos.addAll(especificacoesCorrigidas(atual.especificacoes(), anterior.especificacoes()));
		}
		String resumo = editado ? "usuário corrigiu "
				+ (corrigidos.isEmpty() ? "a representação" : String.join(", ", corrigidos)) + " antes de confirmar"
				: "usuário confirmou os parâmetros";
		Map<String, Object> conclusao = new LinkedHashMap<>();
		conclusao.put("resumo", resumo);
		conclusao.put("editado_pelo_usuario", editado);
		conclusao.put("campos_corrigidos", corrigidos);
		UUID eventoId = UUID.nameUUIDFromBytes(("confirmacao:" + regraId).getBytes(StandardCharsets.UTF_8));
		this.jdbc.update("""
				INSERT INTO trilhas_auditoria (evento_id, job_id, no, concluido_em, regra_id, conclusao)
				VALUES (?, ?, 'confirmacao', ?, ?, ?::jsonb)
				ON CONFLICT (evento_id) DO NOTHING
				""", eventoId, jobId, timestamp, regraId, this.json.writeValueAsString(conclusao));
	}

	private static List<String> camposCorrigidos(NucleoRegraDto atual, NucleoRegraDto anterior) {
		List<String> corrigidos = new ArrayList<>();
		if (!Objects.equals(atual.vigencia(), anterior.vigencia())) {
			corrigidos.add("nucleo.vigencia");
		}
		if (!Objects.equals(atual.loja(), anterior.loja())) {
			corrigidos.add("nucleo.loja");
		}
		if (!Objects.equals(atual.marca(), anterior.marca())) {
			corrigidos.add("nucleo.marca");
		}
		if (!Objects.equals(atual.cargo(), anterior.cargo())) {
			corrigidos.add("nucleo.cargo");
		}
		if (percentualDiferente(atual.percentual(), anterior.percentual())) {
			corrigidos.add("nucleo.percentual");
		}
		return corrigidos;
	}

	private static boolean percentualDiferente(@Nullable BigDecimal atual, @Nullable BigDecimal anterior) {
		if (atual == null || anterior == null) {
			return (atual == null) != (anterior == null);
		}
		return atual.compareTo(anterior) != 0;
	}

	private static List<String> especificacoesCorrigidas(List<JsonNode> atuais, List<JsonNode> anteriores) {
		var refs = new LinkedHashSet<String>();
		atuais.forEach(elemento -> refs.add(elemento.path("ref").asString()));
		anteriores.forEach(elemento -> refs.add(elemento.path("ref").asString()));
		return refs.stream()
			.filter(ref -> !atuais.stream()
				.filter(elemento -> ref.equals(elemento.path("ref").asString()))
				.toList()
				.equals(anteriores.stream().filter(elemento -> ref.equals(elemento.path("ref").asString())).toList()))
			.toList();
	}

	private record DadosDoJob(String origem, BigDecimal orcamento, Instant criadoEm, @Nullable UUID submissaoId,
			@Nullable UUID jobOrigemId) {
	}

	private record VersaoAnterior(UUID id, int versao, String hash, NucleoRegraDto nucleo,
			List<JsonNode> especificacoes) {
	}

}

record ParametrosConfirmadosDto(UUID job_id, UUID regra_id) {
}
