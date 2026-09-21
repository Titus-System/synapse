package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.jspecify.annotations.Nullable;

record JobCriadoDto(UUID id, String status, String origem, List<String> competencias, BigDecimal orcamento,
		Instant criado_em, UUID submissao_id, RegraCriadaDto regra) {
}

record RegraCriadaDto(UUID id, int versao, String origem, RepresentacaoRegraDto representacao, Instant criada_em) {
}

record SimulacaoDto(UUID id, Instant criado_em, @Nullable String status, @Nullable String veredito,
		boolean flag_baixa_rastreabilidade, @Nullable ResultadoSimulacaoDto resultado) {
}

record JobDetalhadoDto(UUID id, String status, String origem, List<String> competencias, BigDecimal orcamento,
		Instant criado_em, @Nullable Instant iniciado_em, @Nullable Instant finalizado_em, UUID submissao_id,
		List<RegraCriadaDto> regras, @Nullable SimulacaoDto simulacao) {
}
