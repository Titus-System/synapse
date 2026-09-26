package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.jspecify.annotations.Nullable;

record PaginaJobsDto(List<JobResumoDto> itens, int pagina, int tamanho, long total) {
}

/**
 * Forma de {@code JobResumo} no contrato HTTP. Campo que ainda não existe fica ausente do
 * JSON, nunca presente como {@code null}.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record JobResumoDto(UUID id, String status, List<String> competencias, BigDecimal orcamento, @Nullable String veredito,
		Instant criado_em, @Nullable Instant finalizado_em, @Nullable UUID job_origem_id) {
}
