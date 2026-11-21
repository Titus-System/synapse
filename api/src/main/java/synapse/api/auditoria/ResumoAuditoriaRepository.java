package synapse.api.auditoria;

import java.math.BigDecimal;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Leitura do resumo do dossiê, sem escrita. As consultas leem só a versão, a origem, o
 * núcleo, as especificações e os parâmetros das regras, e o status, os totais e a meta
 * dos resultados: nenhuma lê {@code resultados_simulacao.linhas},
 * {@code submissoes.binario}, prompts, respostas ou a fonte dos códigos.
 */
@Repository
class ResumoAuditoriaRepository {

	/**
	 * Só as partes que mudaram em relação à versão de {@code regra_origem_id}, que pode
	 * ser de outro job no reprocessamento. Uma chave do núcleo ou dos parâmetros
	 * (orçamento, meta de venda e competências) é a parte {@code nucleo.<chave>}, e um
	 * elemento das especificações é casado pelo {@code ref}. Os parâmetros só entram
	 * quando as duas versões os registram: {@code NULL} quer dizer que a origem da versão
	 * não grava parâmetros, e não que eles foram removidos. Competências ausentes na
	 * origem não contam como incluídas: a versão de extração, e a cópia dela no
	 * reprocessamento, grava só o que o texto disse, enquanto a de correção grava o
	 * conjunto completo do job, em que as competências nunca faltam. A igualdade é a do
	 * {@code jsonb}, e os valores saem como estão gravados; a parte ausente de um dos
	 * lados sai nula. Ordem: núcleo e parâmetros pela chave, depois os elementos pelo
	 * número do {@code ref}.
	 * <p>
	 * A correção renumera os elementos pela posição, e a versão não guarda o {@code ref}
	 * anterior. Por isso a remoção de um elemento que não é o último aparece como
	 * alteração dos seguintes e remoção do último.
	 */
	private static final String ALTERACOES = """
			WITH pares AS (
			    SELECT r.id, r.especificacoes, o.especificacoes AS especificacoes_origem,
			           CASE WHEN jsonb_typeof(r.parametros) = 'object' AND jsonb_typeof(o.parametros) = 'object'
			                THEN r.nucleo || CASE WHEN o.parametros -> 'competencias' IS NULL
			                                      THEN r.parametros - 'competencias'::text ELSE r.parametros END
			                ELSE r.nucleo END AS partes,
			           CASE WHEN jsonb_typeof(r.parametros) = 'object' AND jsonb_typeof(o.parametros) = 'object'
			                THEN o.nucleo || o.parametros ELSE o.nucleo END AS partes_origem
			    FROM regras r
			    JOIN regras o ON o.id = r.regra_origem_id
			    WHERE r.job_id = ?
			)
			SELECT p.id AS regra_id, 0 AS grupo, NULL::numeric AS numero, k.chave AS chave,
			       'nucleo.' || k.chave AS elemento_ref,
			       (p.partes_origem -> k.chave)::text AS anterior, (p.partes -> k.chave)::text AS novo
			FROM pares p
			CROSS JOIN LATERAL (
			    SELECT jsonb_object_keys(p.partes) UNION SELECT jsonb_object_keys(p.partes_origem)
			) AS k(chave)
			WHERE (p.partes_origem -> k.chave) IS DISTINCT FROM (p.partes -> k.chave)
			UNION ALL
			SELECT p.id, 1, substring(e.ref FROM '^elem[.]([0-9]+)$')::numeric, e.ref, e.ref,
			       e.anterior::text, e.novo::text
			FROM pares p
			CROSS JOIN LATERAL (
			    SELECT COALESCE(a.ref, n.ref) AS ref, a.item AS anterior, n.item AS novo
			    FROM (SELECT x.item ->> 'ref' AS ref, x.item
			          FROM jsonb_array_elements(p.especificacoes_origem) AS x(item)) a
			    FULL JOIN (SELECT x.item ->> 'ref' AS ref, x.item
			               FROM jsonb_array_elements(p.especificacoes) AS x(item)) n ON n.ref = a.ref
			) e
			WHERE e.anterior IS DISTINCT FROM e.novo
			ORDER BY regra_id, grupo, numero, chave
			""";

	private final JdbcTemplate jdbc;

	ResumoAuditoriaRepository(JdbcTemplate jdbc) {
		this.jdbc = jdbc;
	}

	List<VersaoLida> listarVersoes(UUID jobId) {
		return this.jdbc.query("""
				SELECT id, versao, regra_origem_id
				FROM regras
				WHERE job_id = ?
				ORDER BY versao
				""", (linha, numero) -> new VersaoLida(Objects.requireNonNull(linha.getObject("id", UUID.class)),
				linha.getInt("versao"), linha.getObject("regra_origem_id", UUID.class)), jobId);
	}

	List<AlteracaoLida> listarAlteracoes(UUID jobId) {
		return this.jdbc.query(ALTERACOES,
				(linha, numero) -> new AlteracaoLida(Objects.requireNonNull(linha.getObject("regra_id", UUID.class)),
						new AlteracaoVersaoDto(Objects.requireNonNull(linha.getString("elemento_ref")),
								linha.getString("anterior"), linha.getString("novo"))),
				jobId);
	}

	/**
	 * Uma linha por simulação registrada; as execuções candidatas da busca da meta não
	 * têm linha em {@code simulacoes}. Os totais só existem com {@code sucesso} e são
	 * lidos como {@code numeric}, com a precisão gravada.
	 */
	List<SimulacaoLida> listarSimulacoes(UUID jobId) {
		return this.jdbc.query("""
				SELECT s.resultado_id, r.versao, rs.status, rs.meta_venda,
				       (rs.totais ->> 'baseline')::numeric AS baseline,
				       (rs.totais ->> 'simulado')::numeric AS simulado,
				       (rs.totais ->> 'diferenca_abs')::numeric AS diferenca_abs,
				       (rs.totais ->> 'diferenca_pct')::numeric AS diferenca_pct,
				       (rs.totais ->> 'orcamento')::numeric AS orcamento
				FROM simulacoes s
				JOIN regras r ON r.id = s.regra_id
				LEFT JOIN resultados_simulacao rs ON rs.id = s.resultado_id AND rs.job_id = s.job_id
				WHERE s.job_id = ?
				ORDER BY s.criado_em, s.id
				""", (linha, numero) -> new SimulacaoLida(linha.getObject("resultado_id", UUID.class),
				linha.getInt("versao"), linha.getString("status"), linha.getBigDecimal("meta_venda"),
				linha.getBigDecimal("baseline"), linha.getBigDecimal("simulado"), linha.getBigDecimal("diferenca_abs"),
				linha.getBigDecimal("diferenca_pct"), linha.getBigDecimal("orcamento")), jobId);
	}

	record VersaoLida(UUID id, int numero, @Nullable UUID regraOrigemId) {
	}

	record AlteracaoLida(UUID regraId, AlteracaoVersaoDto alteracao) {
	}

	/**
	 * {@code resultadoId} e {@code status} são nulos enquanto a simulação não terminou.
	 */
	record SimulacaoLida(@Nullable UUID resultadoId, int versao, @Nullable String status,
			@Nullable BigDecimal metaVenda, @Nullable BigDecimal baseline, @Nullable BigDecimal simulado,
			@Nullable BigDecimal diferencaAbs, @Nullable BigDecimal diferencaPct, @Nullable BigDecimal orcamento) {
	}

}
