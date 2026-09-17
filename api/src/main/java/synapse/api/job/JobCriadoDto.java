package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

record JobCriadoDto(UUID id, String status, String origem, List<String> competencias, BigDecimal orcamento,
		Instant criado_em, UUID submissao_id, RegraCriadaDto regra) {
}

record RegraCriadaDto(UUID id, int versao, String origem, RepresentacaoRegraDto representacao, Instant criada_em) {
}
