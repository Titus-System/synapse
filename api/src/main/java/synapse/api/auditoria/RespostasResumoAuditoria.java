package synapse.api.auditoria;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonRawValue;
import org.jspecify.annotations.Nullable;

/*
 * Forma de ResumoDossieAuditoria no contrato HTTP. Opcional sem valor fica ausente do
 * JSON. Os valores das partes da regra saem como o banco os devolve, e os números saem
 * com a precisão gravada.
 */

@JsonInclude(JsonInclude.Include.NON_NULL)
record ResumoDossieAuditoriaDto(ContagemSimulacoesDto simulacoes, @Nullable Integer versao_vigente,
		List<VersaoResumoAuditoriaDto> versoes, List<ComparacaoSimulacaoDto> comparacoes) {
}

record ContagemSimulacoesDto(long registradas, long sucesso, long falha) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record VersaoResumoAuditoriaDto(UUID id, int numero, @Nullable UUID regra_origem_id,
		List<AlteracaoVersaoDto> alteracoes) {
}

/**
 * A parte incluída não tem {@code anterior}, e a removida não tem {@code novo}. Um valor
 * gravado como {@code null} sai como {@code null}, distinto da ausência.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record AlteracaoVersaoDto(String elemento_ref, @JsonRawValue @Nullable String anterior,
		@JsonRawValue @Nullable String novo) {
}

/**
 * {@code orcamento} e {@code meta_venda} só aparecem quando as duas simulações os têm.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record ComparacaoSimulacaoDto(UUID resultado_id, UUID resultado_anterior_id, VariacaoDto baseline, VariacaoDto simulado,
		VariacaoDto diferenca_abs, VariacaoDto diferenca_pct, @Nullable VariacaoDto orcamento,
		@Nullable VariacaoDto meta_venda) {
}

/** A variação é a diferença exata, sem arredondamento: atual menos anterior. */
record VariacaoDto(BigDecimal anterior, BigDecimal atual, BigDecimal variacao) {

	static VariacaoDto entre(BigDecimal anterior, BigDecimal atual) {
		return new VariacaoDto(anterior, atual, atual.subtract(anterior));
	}

	static @Nullable VariacaoDto entreOpcionais(@Nullable BigDecimal anterior, @Nullable BigDecimal atual) {
		return anterior == null || atual == null ? null : entre(anterior, atual);
	}

}
