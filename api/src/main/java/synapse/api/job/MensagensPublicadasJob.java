package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
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
 * {@code orcamento} e {@code meta_venda} vêm de {@code jobs.orcamento} e
 * {@code jobs.meta_venda} e viajam como escalar porque o codegen não tem permissão nessa
 * tabela. Os dois são opcionais e omitidos quando nulos; ausência não significa zero, e
 * sim que o job não tem o parâmetro - antes da extração, ou porque o usuário não o disse.
 * São {@code BigDecimal} de ponta a ponta - passar por {@code double} perderia precisão
 * de um valor monetário.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record RegraSubmetidaDto(UUID job_id, String origem, List<String> competencias, @Nullable BigDecimal orcamento,
		@Nullable BigDecimal meta_venda, @Nullable UUID submissao_id, @Nullable UUID regra_id) {
}

record ParametrosConfirmadosDto(UUID job_id, UUID regra_id) {
}

/**
 * Forma do evento {@code job-encerrado}, conforme
 * {@code contracts/events/job-encerrado.schema.json}. {@code evento_id} é o id da
 * transição terminal em {@code job_transicoes} e {@code encerrado_em} o instante dela:
 * toda emissão do mesmo encerramento leva os mesmos valores.
 */
record JobEncerradoDto(UUID evento_id, UUID job_id, String status, Instant encerrado_em) {
}
