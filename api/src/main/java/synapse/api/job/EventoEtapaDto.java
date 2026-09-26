package synapse.api.job;

import java.util.UUID;

/**
 * Forma do evento {@code etapa} do contrato HTTP ({@code EventoEtapa}), entregue ao
 * stream SSE. Mesmos três campos de {@link EtapaAlteradaDto}, e ainda assim um record
 * separado: são dois contratos distintos - fila de entrada e HTTP de saída -, e é a
 * separação que impede um campo novo publicado pelo codegen de vazar sozinho para o
 * navegador.
 */
record EventoEtapaDto(UUID job_id, String etapa, String status) {
}
