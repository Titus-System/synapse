package synapse.api.job;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.jspecify.annotations.Nullable;
import tools.jackson.databind.JsonNode;

record VigenciaDto(

		String inicio,

		String fim) {
}

record NucleoSubmissaoDto(

		@Nullable VigenciaDto vigencia,

		List<String> loja,

		List<String> marca,

		List<String> cargo,

		@Nullable BigDecimal percentual) {
}

record ConteudoSubmissaoDto(

		NucleoSubmissaoDto nucleo,

		@Nullable String texto_livre) {
}

/**
 * Todo campo do núcleo é opcional no contrato, e o schema recusa {@code null} explícito:
 * campo ausente tem que sair ausente, como numa extração que não citou loja nem
 * percentual.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record NucleoRegraDto(

		@Nullable VigenciaDto vigencia,

		@Nullable List<String> loja,

		@Nullable List<String> marca,

		@Nullable List<String> cargo,

		@Nullable BigDecimal percentual) {
}

record RepresentacaoRegraDto(

		NucleoRegraDto nucleo,

		List<JsonNode> especificacoes) {
}

/**
 * Os parâmetros da simulação que o usuário disse no texto ou no áudio, no formato de
 * {@code contracts/domain/parametros-simulacao.schema.json}: é o conteúdo de
 * {@code extracoes_regras.parametros} e de {@code regras.parametros}. Não fazem parte da
 * regra - dizem em que condições ela é simulada -, por isso ficam fora de
 * {@link RepresentacaoRegraDto}.
 * <p>
 * Todo campo é opcional, e a ausência é o texto não ter dito o parâmetro. O schema recusa
 * {@code null} explícito, então ausência tem que sair ausente. O valor é o que foi dito,
 * sem restrição de faixa: um orçamento negativo chega até aqui para a validação de
 * domínio apontá-lo como conflito.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record ParametrosDaSimulacao(

		@Nullable BigDecimal orcamento,

		@Nullable BigDecimal meta_venda,

		@Nullable List<String> competencias) {

	static final ParametrosDaSimulacao NENHUM = new ParametrosDaSimulacao(null, null, null);

	/**
	 * O período na forma canônica de {@code jobs.competencias} - ordem crescente, sem
	 * repetição -, ou {@code null} quando o texto não disse período. É o mesmo conjunto
	 * de meses que foi dito, inclusive um mês fora das competências publicadas: ordem e
	 * repetição são forma, não valor, e quem recusa o mês é a validação de domínio. O
	 * artefato do codegen fica como ele o gravou; só a coluna do job é normalizada.
	 */
	@Nullable List<String> periodoCanonico() {
		return (this.competencias != null) ? this.competencias.stream().distinct().sorted().toList() : null;
	}

}

/**
 * Quais parâmetros a extração trouxe, sem os valores. É o que log e métrica podem dizer:
 * nenhum log contém o valor de um parâmetro, e uma tag de métrica tem conjunto limitado.
 */
record ParametrosGravados(boolean orcamento, boolean metaVenda, boolean periodo) {

	static final ParametrosGravados NENHUM = new ParametrosGravados(false, false, false);

	static ParametrosGravados de(ParametrosDaSimulacao parametros) {
		return new ParametrosGravados(parametros.orcamento() != null, parametros.meta_venda() != null,
				parametros.competencias() != null);
	}

}

/**
 * {@code orcamento} fica ausente do JSON num resultado de job sem orçamento, porque o
 * contrato recusa {@code null} explícito.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record TotaisSimulacaoDto(

		BigDecimal baseline,

		BigDecimal simulado,

		BigDecimal diferenca_abs,

		BigDecimal diferenca_pct,

		@Nullable BigDecimal orcamento) {
}

record ResultadoAssercaoDto(

		String nome,

		String resultado,

		@Nullable String detalhe) {
}

/**
 * As quebras absolutas são opcionais no contrato, que recusa {@code null} explícito: um
 * resultado gravado sem elas sai sem elas.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record DecomposicaoResultadoDto(

		Map<String, BigDecimal> elemento,

		Map<String, BigDecimal> loja,

		Map<String, BigDecimal> marca,

		Map<String, BigDecimal> cargo,

		Map<String, BigDecimal> competencia,

		@Nullable Map<String, BigDecimal> matricula,

		@Nullable Map<String, BigDecimal> loja_absoluto,

		@Nullable Map<String, BigDecimal> competencia_absoluto) {
}

record ResultadoSimulacaoDto(

		@Nullable TotaisSimulacaoDto totais,

		List<ResultadoAssercaoDto> assercoes,

		@Nullable DecomposicaoResultadoDto decomposicao) {
}
