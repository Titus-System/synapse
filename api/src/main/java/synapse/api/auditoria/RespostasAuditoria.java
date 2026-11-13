package synapse.api.auditoria;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonRawValue;
import com.fasterxml.jackson.annotation.JsonUnwrapped;
import org.jspecify.annotations.Nullable;

/*
 * Formas de PaginaJobsAuditoria e RegistroAuditoria no contrato HTTP. Opcional sem valor
 * fica ausente do JSON. Os campos jsonb saem como o banco os devolve, sem passar por
 * objetos Java.
 */

record PaginaJobsAuditoriaDto(List<JobAuditoriaDto> itens, int pagina, int tamanho, long total) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record JobAuditoriaDto(UUID id, @Nullable String nome, String status, String origem, List<String> competencias,
		@Nullable BigDecimal orcamento, @Nullable BigDecimal meta_venda, Instant criado_em,
		@Nullable Instant finalizado_em, @Nullable UUID job_origem_id, UsuarioAuditoriaDto usuario) {

	JobAuditoriaDto comNome(@Nullable String nomeResolvido) {
		return new JobAuditoriaDto(this.id, nomeResolvido, this.status, this.origem, this.competencias, this.orcamento,
				this.meta_venda, this.criado_em, this.finalizado_em, this.job_origem_id, this.usuario);
	}

}

record UsuarioAuditoriaDto(String login, String nome) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record JobRegistradoDto(@JsonUnwrapped JobAuditoriaDto job, @Nullable Instant iniciado_em) {
}

record RegistroAuditoriaDto(JobRegistradoDto job, List<EntradaAuditoriaDto> entradas, List<VersaoAuditoriaDto> versoes,
		List<EtapaAuditoriaDto> etapas, List<ChamadaModeloAuditoriaDto> chamadas_modelo,
		List<CodigoAuditoriaDto> codigos, List<ResultadoAuditoriaDto> resultados,
		List<SimulacaoAuditoriaDto> simulacoes, List<TransicaoAuditoriaDto> transicoes, List<AcaoAuditoriaDto> acoes,
		List<RodadaAuditoriaDto> rodadas, List<SugestaoMetaAuditoriaDto> sugestoes_meta,
		List<ExplicacaoAuditoriaDto> explicacoes) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record EntradaAuditoriaDto(UUID id, String tipo, String finalidade, Instant criado_em,
		@JsonRawValue @Nullable String conteudo, @Nullable String texto, @Nullable String formato,
		@Nullable Instant transcrito_em) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record VersaoAuditoriaDto(UUID id, int versao, String origem, @JsonRawValue String representacao, Instant criada_em,
		@Nullable UUID regra_origem_id, String hash, @Nullable Integer tentativa,
		@JsonRawValue @Nullable String parametros) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record EtapaAuditoriaDto(UUID id, String no, Instant concluido_em, @JsonRawValue String conclusao,
		@Nullable UUID regra_id, @Nullable UUID resultado_id, @Nullable UUID prompt_id, @Nullable UUID codigo_gerado_id,
		@Nullable UUID explicacao_id, @Nullable UUID simulacao_id, @Nullable UUID submissao_id) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record ChamadaModeloAuditoriaDto(UUID id, String no, @JsonRawValue String modelo, String prompt, Instant criado_em,
		@Nullable RespostaModeloAuditoriaDto resposta) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record RespostaModeloAuditoriaDto(UUID id, String texto, @JsonRawValue @Nullable String consumo_tokens,
		Instant criado_em) {
}

record CodigoAuditoriaDto(UUID id, UUID regra_id, String linguagem, String fonte, UUID prompt_id, Instant criado_em) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record ResultadoAuditoriaDto(UUID id, UUID codigo_gerado_id, String status, String proposito, @Nullable String veredito,
		@Nullable BigDecimal meta_venda, @JsonRawValue @Nullable String totais, @JsonRawValue String assercoes,
		@JsonRawValue @Nullable String decomposicao, @JsonRawValue @Nullable String diagnostico, Instant criado_em) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record SimulacaoAuditoriaDto(UUID id, UUID regra_id, UUID codigo_gerado_id, @Nullable UUID resultado_id,
		boolean flag_baixa_rastreabilidade, Instant criado_em) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record TransicaoAuditoriaDto(UUID id, @Nullable String status_anterior, String status_novo, Instant ocorrido_em,
		String ator, @Nullable String motivo) {
}

record AcaoAuditoriaDto(UUID id, String acao, Instant executado_em) {
}

/**
 * Forma de {@code Rodada}, que exige {@code rodada_anterior_id}, {@code correcao} e
 * {@code regra_resultante_id} presentes mesmo nulos.
 */
record RodadaAuditoriaDto(UUID id, @Nullable UUID rodada_anterior_id, UUID regra_analisada_id,
		@JsonRawValue String conflitos, @Nullable CorrecaoAuditoriaDto correcao, @Nullable UUID regra_resultante_id,
		String estado, Instant criada_em) {
}

/**
 * {@code texto} sai como {@code null} enquanto a correção por voz não tem transcrição.
 */
record CorrecaoAuditoriaDto(String tipo, @Nullable String texto, Instant enviada_em) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record SugestaoMetaAuditoriaDto(UUID regra_id, @Nullable UUID resultado_id, @Nullable UUID resultado_anterior_id,
		@Nullable String motivo_sem_solucao, Instant criada_em, @Nullable Instant aceita_em) {
}

record ExplicacaoAuditoriaDto(UUID id, UUID resultado_id, String texto, boolean aderencia_conferida,
		Instant criado_em) {
}

record ErroAuditoriaDto(String codigo, String mensagem) {
}
