package synapse.api.auditoria;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
class EventosAuditoriaRepository {

	// Formulário mantém seu evento, mas o contrato só aceita texto/voz em tipo_entrada.
	private static final String FONTES = """
			WITH entradas AS (
			    SELECT id AS job_id, submissao_id FROM jobs WHERE submissao_id IS NOT NULL
			    UNION
			    SELECT job_id, submissao_correcao_id FROM rodadas_correcao WHERE submissao_correcao_id IS NOT NULL
			), eventos AS (
			    SELECT j.id AS job_id, s.criado_em AS instante, 'entrada'::text AS tipo,
			           'usuario'::text AS autor, s.id AS origem_id,
			           CASE WHEN s.id = j.submissao_id THEN 'entrada_inicial' ELSE 'correcao' END AS finalidade,
			           CASE WHEN s.tipo IN ('texto', 'voz') THEN s.tipo END AS tipo_entrada,
			           NULL::text AS origem_versao, NULL::integer AS versao,
			           NULL::text AS status, NULL::text AS veredito, NULL::text AS acao
			    FROM entradas entrada
			    JOIN jobs j ON j.id = entrada.job_id
			    JOIN submissoes s ON s.id = entrada.submissao_id
			    UNION ALL
			    SELECT job_id, criada_em, 'rodada_correcao', 'sistema', id,
			           NULL, NULL, NULL, NULL, NULL, NULL, NULL
			    FROM rodadas_correcao
			    UNION ALL
			    SELECT job_id, criada_em, 'versao_regra',
			           CASE WHEN origem IN ('confirmacao_usuario', 'reprocessamento') THEN 'usuario' ELSE 'sistema' END,
			           id, NULL, NULL, origem, versao, NULL, NULL, NULL
			    FROM regras
			    UNION ALL
			    SELECT job_id, criado_em, 'codigo_gerado', 'sistema', id,
			           NULL, NULL, NULL, NULL, NULL, NULL, NULL
			    FROM codigos_gerados
			    UNION ALL
			    SELECT job_id, criado_em, 'resultado_simulacao', 'sistema', id,
			           NULL, NULL, NULL, NULL, status, veredito, NULL
			    FROM resultados_simulacao
			    WHERE proposito = 'simulacao'
			    UNION ALL
			    SELECT job_id, criada_em, 'sugestao_meta_criada', 'sistema', regra_id,
			           NULL, NULL, NULL, NULL, NULL, NULL, NULL
			    FROM sugestoes_meta_venda
			    WHERE motivo_sem_solucao IS NULL
			    UNION ALL
			    SELECT job_id, aceita_em, 'sugestao_meta_aceita', 'usuario', regra_id,
			           NULL, NULL, NULL, NULL, NULL, NULL, NULL
			    FROM sugestoes_meta_venda
			    WHERE aceita_em IS NOT NULL
			    UNION ALL
			    SELECT job_id, executado_em, 'acao_usuario', 'usuario', id,
			           NULL, NULL, NULL, NULL, NULL, NULL, acao
			    FROM job_acoes
			    UNION ALL
			    SELECT job_id, ocorrido_em, 'job_erro',
			           CASE WHEN ator = 'usuario' THEN 'usuario' ELSE 'sistema' END,
			           id, NULL, NULL, NULL, NULL, NULL, NULL, NULL
			    FROM job_transicoes
			    WHERE status_novo = 'erro'
			), ultimas_regras AS (
			    SELECT DISTINCT ON (job_id) job_id, nucleo
			    FROM regras
			    ORDER BY job_id, versao DESC
			)
			""";

	private static final String FILTRADOS = FONTES + """
			, jobs_filtrados AS (
			    SELECT j.id AS job_id, j.usuario_id, u.login AS usuario_login, j.status AS job_status,
			           COALESCE(CAST(:loja AS text), ultima.nucleo->'loja'->>0) AS loja,
			           COALESCE(CAST(:marca AS text), ultima.nucleo->'marca'->>0) AS marca,
			           COALESCE(CAST(:cargo AS text), ultima.nucleo->'cargo'->>0) AS cargo
			    FROM jobs j
			    JOIN usuarios u ON u.id = j.usuario_id
			    LEFT JOIN ultimas_regras ultima ON ultima.job_id = j.id
			    LEFT JOIN LATERAL (
			        WITH RECURSIVE cadeia AS (
			            SELECT j.submissao_id, j.job_origem_id, 0 AS nivel
			            WHERE CAST(:nome_padrao AS text) IS NOT NULL AND j.nome IS NULL
			            UNION ALL
			            SELECT o.submissao_id, o.job_origem_id, c.nivel + 1
			            FROM cadeia c
			            JOIN jobs o ON o.id = c.job_origem_id
			            WHERE c.submissao_id IS NULL
			        )
			        SELECT si.transcricao
			        FROM cadeia c
			        JOIN submissoes si ON si.id = c.submissao_id
			        ORDER BY c.nivel
			        LIMIT 1
			    ) inicial ON true
			    WHERE (CAST(:usuario AS text) IS NULL OR u.login = :usuario)
			      AND (CAST(:job_id AS uuid) IS NULL OR j.id = CAST(:job_id AS uuid))
			      AND (CAST(:loja AS text) IS NULL
			           OR ultima.nucleo->'loja' @> jsonb_build_array(CAST(:loja AS text)))
			      AND (CAST(:marca AS text) IS NULL
			           OR ultima.nucleo->'marca' @> jsonb_build_array(CAST(:marca AS text)))
			      AND (CAST(:cargo AS text) IS NULL
			           OR ultima.nucleo->'cargo' @> jsonb_build_array(CAST(:cargo AS text)))
			      AND (CAST(:nome_padrao AS text) IS NULL OR COALESCE(j.nome, NULLIF(left(
			          regexp_replace(btrim(inicial.transcricao, E' \\t\\r\\n'), '[ \\t\\r\\n]+', ' ', 'g'),
			          50), '')) ILIKE :nome_padrao ESCAPE '!')
			), eventos_filtrados AS (
			    SELECT e.job_id, e.instante, e.tipo, e.autor, e.origem_id, e.finalidade, e.tipo_entrada,
			           e.origem_versao, e.versao, e.status, e.veredito, e.acao,
			           j.usuario_id, j.usuario_login, j.job_status, j.loja, j.marca, j.cargo
			    FROM eventos e
			    JOIN jobs_filtrados j ON j.job_id = e.job_id
			    WHERE CAST(:mes AS text) IS NULL
			       OR to_char(e.instante AT TIME ZONE 'America/Sao_Paulo', 'YYYY-MM') = :mes
			)
			""";

	private final NamedParameterJdbcTemplate jdbc;

	EventosAuditoriaRepository(JdbcTemplate jdbc) {
		this.jdbc = new NamedParameterJdbcTemplate(jdbc);
	}

	ContadoresEventosAuditoriaDto contar(ConsultaEventosAuditoria filtros) {
		return Objects.requireNonNull(this.jdbc.queryForObject(
				FILTRADOS
						+ """
								SELECT count(*) AS eventos, count(DISTINCT usuario_id) AS usuarios,
								       count(DISTINCT job_id) AS regras,
								       count(*) FILTER (WHERE tipo = 'resultado_simulacao' AND status <> 'sucesso') AS simulacoes_com_falha
								FROM eventos_filtrados
								""",
				parametros(filtros), (linha, numero) -> new ContadoresEventosAuditoriaDto(linha.getLong("eventos"),
						linha.getLong("usuarios"), linha.getLong("regras"), linha.getLong("simulacoes_com_falha"))));
	}

	List<EventoAuditoriaDto> listar(ConsultaEventosAuditoria filtros, PaginaAuditoria pagina) {
		MapSqlParameterSource parametros = parametros(filtros).addValue("tamanho", pagina.tamanho())
			.addValue("deslocamento", pagina.deslocamento());
		return this.jdbc.query(FILTRADOS + """
				SELECT instante, tipo, autor, usuario_login, job_id, job_status, origem_id, loja, marca, cargo,
				       finalidade, tipo_entrada, origem_versao, versao, status, veredito, acao
				FROM eventos_filtrados
				ORDER BY instante DESC, origem_id DESC, tipo DESC, job_id DESC
				LIMIT :tamanho OFFSET :deslocamento
				""", parametros, (linha, numero) -> evento(linha));
	}

	FiltrosEventosAuditoriaDto consultarFiltros() {
		return Objects.requireNonNull(this.jdbc.queryForObject(
				FONTES + """
						SELECT ARRAY(
						    SELECT DISTINCT u.login FROM usuarios u JOIN jobs j ON j.usuario_id = u.id ORDER BY u.login
						) AS usuarios,
						ARRAY(
						    SELECT DISTINCT to_char(instante AT TIME ZONE 'America/Sao_Paulo', 'YYYY-MM') AS mes
						    FROM eventos ORDER BY mes
						) AS meses,
						ARRAY(
						    SELECT DISTINCT codigo.valor FROM ultimas_regras ultima
						    CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(ultima.nucleo->'loja', '[]'::jsonb)) codigo(valor)
						    ORDER BY codigo.valor
						) AS lojas,
						ARRAY(
						    SELECT DISTINCT codigo.valor FROM ultimas_regras ultima
						    CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(ultima.nucleo->'marca', '[]'::jsonb)) codigo(valor)
						    ORDER BY codigo.valor
						) AS marcas,
						ARRAY(
						    SELECT DISTINCT codigo.valor FROM ultimas_regras ultima
						    CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(ultima.nucleo->'cargo', '[]'::jsonb)) codigo(valor)
						    ORDER BY codigo.valor
						) AS cargos
						""",
				new MapSqlParameterSource(),
				(linha, numero) -> new FiltrosEventosAuditoriaDto(textos(linha, "usuarios"), textos(linha, "meses"),
						textos(linha, "lojas"), textos(linha, "marcas"), textos(linha, "cargos"))));
	}

	private static MapSqlParameterSource parametros(ConsultaEventosAuditoria filtros) {
		return new MapSqlParameterSource().addValue("usuario", filtros.usuario(), Types.VARCHAR)
			.addValue("mes", filtros.mes(), Types.VARCHAR)
			.addValue("loja", filtros.loja(), Types.VARCHAR)
			.addValue("marca", filtros.marca(), Types.VARCHAR)
			.addValue("cargo", filtros.cargo(), Types.VARCHAR)
			.addValue("job_id", filtros.jobId(), Types.OTHER)
			.addValue("nome_padrao", filtros.nomePadrao(), Types.VARCHAR);
	}

	private static EventoAuditoriaDto evento(ResultSet linha) throws SQLException {
		return new EventoAuditoriaDto(
				Objects.requireNonNull(linha.getObject("instante", OffsetDateTime.class)).toInstant(),
				texto(linha, "tipo"), texto(linha, "autor"), texto(linha, "usuario_login"),
				new JobEventoAuditoriaDto(uuid(linha, "job_id"), null, texto(linha, "job_status")),
				uuid(linha, "origem_id"), linha.getString("loja"), linha.getString("marca"), linha.getString("cargo"),
				linha.getString("finalidade"), linha.getString("tipo_entrada"), linha.getString("origem_versao"),
				linha.getObject("versao", Integer.class), linha.getString("status"), linha.getString("veredito"),
				linha.getString("acao"));
	}

	private static UUID uuid(ResultSet linha, String coluna) throws SQLException {
		return Objects.requireNonNull(linha.getObject(coluna, UUID.class));
	}

	private static String texto(ResultSet linha, String coluna) throws SQLException {
		return Objects.requireNonNull(linha.getString(coluna));
	}

	private static List<String> textos(ResultSet linha, String coluna) throws SQLException {
		return List.of((String[]) Objects.requireNonNull(linha.getArray(coluna)).getArray());
	}

}
