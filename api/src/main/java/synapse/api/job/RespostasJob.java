package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonRawValue;
import org.jspecify.annotations.Nullable;

/**
 * Forma de {@code Job} no contrato HTTP, a resposta da criação, da confirmação e do
 * reprocessamento.
 * <p>
 * {@code orcamento} é nulável porque {@code jobs.orcamento} passou a ser, embora o
 * contrato ainda o declare obrigatório aqui: as três origens que respondem este corpo -
 * formulário, confirmação e reprocessamento - sempre têm um. Um job sem orçamento só
 * nasce por texto ou voz, que não passa por nenhuma delas; o que o contrato faz quando
 * passar é decisão da T-281.
 */
record JobCriadoDto(UUID id, String status, String origem, List<String> competencias,
		@JsonInclude(JsonInclude.Include.NON_NULL) @Nullable BigDecimal orcamento, Instant criado_em,
		@JsonInclude(JsonInclude.Include.NON_NULL) @Nullable UUID submissao_id,
		@JsonInclude(JsonInclude.Include.NON_NULL) @Nullable UUID job_origem_id, RegraCriadaDto regra) {
}

record RegraCriadaDto(UUID id, int versao, String origem, RepresentacaoRegraDto representacao, Instant criada_em) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record SimulacaoDto(UUID id, UUID regra_id, Instant criado_em, String status, @Nullable String veredito,
		boolean flag_baixa_rastreabilidade, @Nullable ResultadoSimulacaoDto resultado) {
}

/**
 * Forma de {@code JobDetalhado} no contrato HTTP. {@code orcamento} e {@code meta_venda}
 * são os parâmetros da simulação deste job: ficam ausentes do JSON quando o job não os
 * tem, que é o caso antes da extração e quando o usuário não os disse.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record JobDetalhadoDto(UUID id, String status, String origem, List<String> competencias, @Nullable BigDecimal orcamento,
		@Nullable BigDecimal meta_venda, Instant criado_em, @Nullable Instant iniciado_em,
		@Nullable Instant finalizado_em, @Nullable UUID submissao_id, @Nullable UUID job_origem_id,
		@Nullable String motivo, List<RegraCriadaDto> regras, @Nullable SimulacaoDto simulacao,
		List<SimulacaoDto> simulacoes) {
}

record PaginaJobsDto(List<JobResumoDto> itens, int pagina, int tamanho, long total) {
}

/**
 * Forma de {@code DetalhamentoSimulacao}. {@code linhas} é o jsonb repassado como foi
 * gravado, sem passar por objetos Java, e fica ausente quando a simulação não tem
 * detalhamento.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record DetalhamentoSimulacaoDto(UUID simulacao_id, @JsonRawValue @Nullable String linhas) {
}

/**
 * Forma de {@code JobResumo} no contrato HTTP. Campo que ainda não existe fica ausente do
 * JSON, nunca presente como {@code null}.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record JobResumoDto(UUID id, String status, List<String> competencias, @Nullable BigDecimal orcamento,
		@Nullable BigDecimal meta_venda, @Nullable String veredito, Instant criado_em, @Nullable Instant finalizado_em,
		@Nullable UUID job_origem_id) {
}

/**
 * Corpo de erro conforme {@code components/schemas/Erro} do contrato HTTP: {@code codigo}
 * é o que o cliente decide em cima, {@code mensagem} é texto que o domínio decidiu expor
 * - nunca detalhe interno.
 */
record ErroDto(String codigo, String mensagem) {
}

record ErroCriarJobDto(String codigo, String mensagem,
		@JsonInclude(JsonInclude.Include.NON_EMPTY) List<ElementoErroDto> elementos) {
}

record ElementoErroDto(String ref, String motivo) {
}
