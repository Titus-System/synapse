package synapse.api.job;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import org.jspecify.annotations.Nullable;

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

record NucleoRegraDto(

		@Nullable VigenciaDto vigencia,

		@Nullable List<String> loja,

		@Nullable List<String> marca,

		@Nullable List<String> cargo,

		@Nullable BigDecimal percentual) {
}

record EspecificacaoRegraDto(

		String ref,

		String construto) {
}

record RepresentacaoRegraDto(

		NucleoRegraDto nucleo,

		List<EspecificacaoRegraDto> especificacoes) {
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

record DecomposicaoResultadoDto(

		Map<String, BigDecimal> elemento,

		Map<String, BigDecimal> loja,

		Map<String, BigDecimal> marca,

		Map<String, BigDecimal> cargo,

		Map<String, BigDecimal> competencia) {
}

record ResultadoSimulacaoDto(

		TotaisSimulacaoDto totais,

		List<ResultadoAssercaoDto> assercoes,

		DecomposicaoResultadoDto decomposicao) {
}
