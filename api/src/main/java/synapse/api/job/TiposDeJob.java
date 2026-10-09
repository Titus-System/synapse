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

record TotaisSimulacaoDto(

		BigDecimal baseline,

		BigDecimal simulado,

		BigDecimal diferenca_abs,

		BigDecimal diferenca_pct,

		BigDecimal orcamento) {
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
