package synapse.api.auditoria;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Leitura das tabelas do job para o auditor, sem escrita e sem as classes da fatia
 * {@code job}. Nenhuma consulta lê {@code submissoes.binario} nem
 * {@code resultados_simulacao.linhas}. Cada seção do registro é uma consulta filtrada
 * pelo job e em ordem cronológica, com o id como desempate.
 */
@Repository
class AuditoriaRepository {

	private static final String JOB = """
			SELECT j.id, j.status,
			       CASE WHEN j.job_origem_id IS NOT NULL THEN 'reprocessamento' ELSE s.tipo END AS origem,
			       j.competencias, j.orcamento, j.meta_venda, j.criado_em, j.iniciado_em, j.finalizado_em,
			       j.job_origem_id, u.login, u.nome AS usuario_nome
			FROM jobs j
			JOIN usuarios u ON u.id = j.usuario_id
			LEFT JOIN submissoes s ON s.id = j.submissao_id
			""";

	private final JdbcTemplate jdbc;

	AuditoriaRepository(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	long contarJobs() {
		return Objects.requireNonNull(this.jdbc.queryForObject("SELECT count(*) FROM jobs", Long.class));
	}

	List<JobLido> listarJobs(int tamanho, long deslocamento) {
		return this.jdbc.query(JOB + "ORDER BY j.criado_em DESC, j.id DESC LIMIT ? OFFSET ?",
				(linha, numero) -> job(linha), tamanho, deslocamento);
	}

	List<JobLido> buscarJob(UUID jobId) {
		return this.jdbc.query(JOB + "WHERE j.id = ?", (linha, numero) -> job(linha), jobId);
	}

	/**
	 * A submissão inicial do job e as das correções enviadas nas rodadas. O job
	 * reprocessado não tem submissão própria.
	 */
	List<EntradaAuditoriaDto> listarEntradas(UUID jobId) {
		return this.jdbc.query("""
				SELECT s.id, s.tipo,
				       CASE WHEN s.id = j.submissao_id THEN 'entrada_inicial' ELSE 'correcao' END AS finalidade,
				       s.criado_em, s.conteudo::text AS conteudo, s.transcricao, s.formato, s.transcrito_em
				FROM jobs j
				JOIN submissoes s ON s.id = j.submissao_id
				    OR s.id IN (SELECT r.submissao_correcao_id FROM rodadas_correcao r WHERE r.job_id = j.id)
				WHERE j.id = ?
				ORDER BY s.criado_em, s.id
				""",
				(linha, numero) -> new EntradaAuditoriaDto(uuid(linha, "id"), texto(linha, "tipo"),
						texto(linha, "finalidade"), momento(linha, "criado_em"), linha.getString("conteudo"),
						linha.getString("transcricao"), linha.getString("formato"), instante(linha, "transcrito_em")),
				jobId);
	}

	/**
	 * {@code representacao} é o artefato completo quando a versão o tem, e o núcleo com
	 * as especificações nas versões anteriores à coluna.
	 */
	List<VersaoAuditoriaDto> listarVersoes(UUID jobId) {
		return this.jdbc.query(
				"""
						SELECT id, versao, origem, regra_origem_id, hash, tentativa, criada_em, parametros::text AS parametros,
						       COALESCE(representacao,
						           jsonb_build_object('nucleo', nucleo, 'especificacoes', especificacoes))::text AS representacao
						FROM regras
						WHERE job_id = ?
						ORDER BY criada_em, versao
						""",
				(linha, numero) -> new VersaoAuditoriaDto(uuid(linha, "id"), linha.getInt("versao"),
						texto(linha, "origem"), texto(linha, "representacao"), momento(linha, "criada_em"),
						linha.getObject("regra_origem_id", UUID.class), texto(linha, "hash"),
						linha.getObject("tentativa", Integer.class), linha.getString("parametros")),
				jobId);
	}

	/**
	 * A simulação vem da linha quando ela a traz e, senão, do código do resultado
	 * apontado, porque {@code simulacoes.codigo_gerado_id} é único. A submissão da
	 * extração inicial é a da extração gravada com a resposta do prompt da linha. A da
	 * reextração é a correção da rodada que analisou a versão da linha, a última enviada
	 * até a conclusão: depois de uma reextração que falhou, a rodada seguinte analisa a
	 * mesma versão.
	 */
	List<EtapaAuditoriaDto> listarEtapas(UUID jobId) {
		return this.jdbc.query("""
				SELECT t.id, t.no, t.concluido_em, t.conclusao::text AS conclusao, t.regra_id, t.resultado_id,
				       t.prompt_id, t.codigo_gerado_id, t.explicacao_id,
				       COALESCE(t.simulacao_id, (
				           SELECT s.id FROM resultados_simulacao rs
				           JOIN simulacoes s ON s.codigo_gerado_id = rs.codigo_gerado_id AND s.job_id = rs.job_id
				           WHERE rs.id = t.resultado_id AND rs.job_id = t.job_id
				       )) AS simulacao_id,
				       CASE WHEN t.no = 'extracao_parametros' THEN COALESCE((
				           SELECT e.submissao_id FROM respostas_modelo rm
				           JOIN extracoes_regras e ON e.resposta_id = rm.id AND e.job_id = rm.job_id
				           WHERE rm.prompt_id = t.prompt_id AND rm.job_id = t.job_id
				           ORDER BY e.criado_em, e.id
				           LIMIT 1
				       ), (
				           SELECT r.submissao_correcao_id FROM rodadas_correcao r
				           JOIN submissoes s ON s.id = r.submissao_correcao_id
				           WHERE r.job_id = t.job_id AND r.regra_analisada_id = t.regra_id
				             AND s.criado_em <= t.concluido_em
				           ORDER BY s.criado_em DESC, s.id DESC
				           LIMIT 1
				       )) END AS submissao_id
				FROM trilhas_auditoria t
				WHERE t.job_id = ?
				ORDER BY t.concluido_em, t.id
				""", (linha, numero) -> new EtapaAuditoriaDto(uuid(linha, "id"), texto(linha, "no"),
				momento(linha, "concluido_em"), texto(linha, "conclusao"), linha.getObject("regra_id", UUID.class),
				linha.getObject("resultado_id", UUID.class), linha.getObject("prompt_id", UUID.class),
				linha.getObject("codigo_gerado_id", UUID.class), linha.getObject("explicacao_id", UUID.class),
				linha.getObject("simulacao_id", UUID.class), linha.getObject("submissao_id", UUID.class)), jobId);
	}

	List<ChamadaModeloAuditoriaDto> listarChamadasModelo(UUID jobId) {
		return this.jdbc.query("""
				SELECT p.id, p.no, p.modelo::text AS modelo, p.conteudo AS prompt, p.criado_em,
				       rm.id AS resposta_id, rm.conteudo AS resposta, rm.consumo_tokens::text AS consumo_tokens,
				       rm.criado_em AS respondido_em
				FROM prompts p
				LEFT JOIN respostas_modelo rm ON rm.prompt_id = p.id AND rm.job_id = p.job_id
				WHERE p.job_id = ?
				ORDER BY p.criado_em, p.id
				""", (linha, numero) -> {
			UUID respostaId = linha.getObject("resposta_id", UUID.class);
			RespostaModeloAuditoriaDto resposta = respostaId == null ? null : new RespostaModeloAuditoriaDto(respostaId,
					texto(linha, "resposta"), linha.getString("consumo_tokens"), momento(linha, "respondido_em"));
			return new ChamadaModeloAuditoriaDto(uuid(linha, "id"), texto(linha, "no"), texto(linha, "modelo"),
					texto(linha, "prompt"), momento(linha, "criado_em"), resposta);
		}, jobId);
	}

	List<CodigoAuditoriaDto> listarCodigos(UUID jobId) {
		return this.jdbc.query("""
				SELECT id, regra_id, linguagem, fonte, prompt_id, criado_em
				FROM codigos_gerados
				WHERE job_id = ?
				ORDER BY criado_em, id
				""",
				(linha, numero) -> new CodigoAuditoriaDto(uuid(linha, "id"), uuid(linha, "regra_id"),
						texto(linha, "linguagem"), texto(linha, "fonte"), uuid(linha, "prompt_id"),
						momento(linha, "criado_em")),
				jobId);
	}

	/** Inclui as execuções candidatas da busca da meta, que não têm simulação própria. */
	List<ResultadoAuditoriaDto> listarResultados(UUID jobId) {
		return this.jdbc.query("""
				SELECT id, codigo_gerado_id, status, proposito, veredito, meta_venda, criado_em,
				       totais::text AS totais, assercoes::text AS assercoes, decomposicao::text AS decomposicao,
				       diagnostico::text AS diagnostico
				FROM resultados_simulacao
				WHERE job_id = ?
				ORDER BY criado_em, id
				""",
				(linha, numero) -> new ResultadoAuditoriaDto(uuid(linha, "id"), uuid(linha, "codigo_gerado_id"),
						texto(linha, "status"), texto(linha, "proposito"), linha.getString("veredito"),
						linha.getBigDecimal("meta_venda"), linha.getString("totais"), texto(linha, "assercoes"),
						linha.getString("decomposicao"), linha.getString("diagnostico"), momento(linha, "criado_em")),
				jobId);
	}

	List<SimulacaoAuditoriaDto> listarSimulacoes(UUID jobId) {
		return this.jdbc.query("""
				SELECT id, regra_id, codigo_gerado_id, resultado_id, flag_baixa_rastreabilidade, criado_em
				FROM simulacoes
				WHERE job_id = ?
				ORDER BY criado_em, id
				""",
				(linha, numero) -> new SimulacaoAuditoriaDto(uuid(linha, "id"), uuid(linha, "regra_id"),
						uuid(linha, "codigo_gerado_id"), linha.getObject("resultado_id", UUID.class),
						linha.getBoolean("flag_baixa_rastreabilidade"), momento(linha, "criado_em")),
				jobId);
	}

	List<TransicaoAuditoriaDto> listarTransicoes(UUID jobId) {
		return this.jdbc.query("""
				SELECT id, status_anterior, status_novo, ocorrido_em, ator, motivo
				FROM job_transicoes
				WHERE job_id = ?
				ORDER BY ocorrido_em, id
				""",
				(linha, numero) -> new TransicaoAuditoriaDto(uuid(linha, "id"), linha.getString("status_anterior"),
						texto(linha, "status_novo"), momento(linha, "ocorrido_em"), texto(linha, "ator"),
						linha.getString("motivo")),
				jobId);
	}

	List<AcaoAuditoriaDto> listarAcoes(UUID jobId) {
		return this.jdbc.query("""
				SELECT id, acao, executado_em
				FROM job_acoes
				WHERE job_id = ?
				ORDER BY executado_em, id
				""", (linha, numero) -> new AcaoAuditoriaDto(uuid(linha, "id"), texto(linha, "acao"),
				momento(linha, "executado_em")), jobId);
	}

	List<RodadaAuditoriaDto> listarRodadas(UUID jobId) {
		return this.jdbc.query("""
				SELECT r.id, r.rodada_anterior_id, r.regra_analisada_id, r.conflitos::text AS conflitos, r.estado,
				       r.regra_resultante_id, r.criada_em, s.id AS submissao_id, s.tipo, s.transcricao,
				       s.criado_em AS enviada_em
				FROM rodadas_correcao r
				LEFT JOIN submissoes s ON s.id = r.submissao_correcao_id
				WHERE r.job_id = ?
				ORDER BY r.criada_em, r.id
				""", (linha, numero) -> {
			CorrecaoAuditoriaDto correcao = linha.getObject("submissao_id", UUID.class) == null ? null
					: new CorrecaoAuditoriaDto(texto(linha, "tipo"), linha.getString("transcricao"),
							momento(linha, "enviada_em"));
			return new RodadaAuditoriaDto(uuid(linha, "id"), linha.getObject("rodada_anterior_id", UUID.class),
					uuid(linha, "regra_analisada_id"), texto(linha, "conflitos"), correcao,
					linha.getObject("regra_resultante_id", UUID.class), texto(linha, "estado"),
					momento(linha, "criada_em"));
		}, jobId);
	}

	List<SugestaoMetaAuditoriaDto> listarSugestoesMeta(UUID jobId) {
		return this.jdbc.query("""
				SELECT regra_id, resultado_id, resultado_anterior_id, motivo_sem_solucao, criada_em, aceita_em
				FROM sugestoes_meta_venda
				WHERE job_id = ?
				ORDER BY criada_em, regra_id
				""", (linha, numero) -> new SugestaoMetaAuditoriaDto(uuid(linha, "regra_id"),
				linha.getObject("resultado_id", UUID.class), linha.getObject("resultado_anterior_id", UUID.class),
				linha.getString("motivo_sem_solucao"), momento(linha, "criada_em"), instante(linha, "aceita_em")),
				jobId);
	}

	/** Conferidas e reprovadas: só o auditor vê a narrativa reprovada. */
	List<ExplicacaoAuditoriaDto> listarExplicacoes(UUID jobId) {
		return this.jdbc.query("""
				SELECT e.id, e.resultado_id, e.texto, e.aderencia_conferida, e.criado_em
				FROM explicacoes e
				JOIN resultados_simulacao rs ON rs.id = e.resultado_id
				WHERE rs.job_id = ?
				ORDER BY e.criado_em, e.id
				""",
				(linha, numero) -> new ExplicacaoAuditoriaDto(uuid(linha, "id"), uuid(linha, "resultado_id"),
						texto(linha, "texto"), linha.getBoolean("aderencia_conferida"), momento(linha, "criado_em")),
				jobId);
	}

	private static JobLido job(ResultSet linha) throws SQLException {
		JobAuditoriaDto job = new JobAuditoriaDto(uuid(linha, "id"), null, texto(linha, "status"),
				texto(linha, "origem"), List.of((String[]) linha.getArray("competencias").getArray()),
				linha.getBigDecimal("orcamento"), linha.getBigDecimal("meta_venda"), momento(linha, "criado_em"),
				instante(linha, "finalizado_em"), linha.getObject("job_origem_id", UUID.class),
				new UsuarioAuditoriaDto(texto(linha, "login"), texto(linha, "usuario_nome")));
		return new JobLido(job, instante(linha, "iniciado_em"));
	}

	private static UUID uuid(ResultSet linha, String coluna) throws SQLException {
		return Objects.requireNonNull(linha.getObject(coluna, UUID.class));
	}

	private static String texto(ResultSet linha, String coluna) throws SQLException {
		return Objects.requireNonNull(linha.getString(coluna));
	}

	private static Instant momento(ResultSet linha, String coluna) throws SQLException {
		return Objects.requireNonNull(instante(linha, coluna));
	}

	private static @Nullable Instant instante(ResultSet linha, String coluna) throws SQLException {
		OffsetDateTime valor = linha.getObject(coluna, OffsetDateTime.class);
		return valor == null ? null : valor.toInstant();
	}

	/** {@code iniciadoEm} só sai no registro do job, não na listagem. */
	record JobLido(JobAuditoriaDto job, @Nullable Instant iniciadoEm) {
	}

}
