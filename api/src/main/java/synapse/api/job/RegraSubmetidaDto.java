package synapse.api.job;

import java.math.BigDecimal;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.jspecify.annotations.Nullable;

/**
 * Forma do evento {@code regra-submetida} (fila, não HTTP), conforme
 * {@code contracts/events/regra-submetida.schema.json}. {@code submissao_id} e
 * {@code regra_id} ficam ausentes do JSON quando nulos, nunca presentes como {@code null}
 * - o schema recusa {@code null} explícito, e a condição de presença de cada um depende
 * de {@code origem} (ausente na {@code voz} para {@code regra_id}, sempre presente na
 * {@code formulario}).
 * <p>
 * {@code orcamento} vem de {@code jobs.orcamento} e viaja como escalar porque o codegen
 * não tem permissão nessa tabela. Também é opcional e omitido quando nulo; ausência não
 * significa zero. É {@code BigDecimal} de ponta a ponta - passar por {@code double}
 * perderia precisão de um valor monetário.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record RegraSubmetidaDto(UUID job_id, String origem, List<String> competencias, @Nullable BigDecimal orcamento,
		@Nullable UUID submissao_id, @Nullable UUID regra_id) {
}
