package synapse.api.job;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import tools.jackson.core.StreamWriteFeature;
import tools.jackson.databind.MapperFeature;
import tools.jackson.databind.cfg.JsonNodeFeature;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.stereotype.Component;

final class HashDaRegra {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(MapperFeature.SORT_PROPERTIES_ALPHABETICALLY)
		.disable(MapperFeature.SORT_CREATOR_PROPERTIES_FIRST)
		.enable(StreamWriteFeature.WRITE_BIGDECIMAL_AS_PLAIN)
		.enable(JsonNodeFeature.WRITE_PROPERTIES_SORTED)
		.build();

	private HashDaRegra() {
	}

	static String calcular(RepresentacaoRegraDto regra) {
		NucleoRegraDto nucleo = regra.nucleo();
		NucleoRegraDto canonico = new NucleoRegraDto(nucleo.vigencia(), nucleo.loja(), nucleo.marca(), nucleo.cargo(),
				Objects.requireNonNull(nucleo.percentual()).stripTrailingZeros());
		byte[] json = JSON.writeValueAsString(new RepresentacaoRegraDto(canonico, regra.especificacoes()))
			.getBytes(StandardCharsets.UTF_8);
		try {
			return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json));
		}
		catch (NoSuchAlgorithmException ex) {
			throw new IllegalStateException("SHA-256 indisponível.", ex);
		}
	}

}

/**
 * Resolve a versão de {@code regras} de um job: reaproveita a linha de mesmo hash ou
 * insere a próxima. Único lugar que escreve na tabela, para que a regra de deduplicação e
 * a numeração da versão não se repitam por caminho de entrada - hoje a confirmação do
 * usuário e a sugestão de adaptação, que só diferem em {@code origem} e na versão de que
 * derivam.
 *
 * <p>
 * A deduplicação por {@code (job_id, hash)} é o que faz reenviar a mesma representação
 * não criar versão nova: é ela que sustenta o índice único da migration {@code 006} e o
 * caminho em que o usuário confirma sem ter editado nada.
 */
@Component
class VersoesDaRegra {

	private final JobRepository repository;

	VersoesDaRegra(JobRepository repository) {
		this.repository = repository;
	}

	VersaoRegra resolver(UUID jobId, RepresentacaoRegraDto representacao, String hash, String origem,
			@Nullable UUID origemId, Timestamp timestamp, Instant agora) {
		List<VersaoRegra> existentes = this.repository.buscarRegraPorHash(jobId, hash);
		if (!existentes.isEmpty()) {
			return existentes.getFirst();
		}

		int novaVersao = proximaVersao(jobId);
		UUID id = this.repository.inserirVersaoRegra(jobId, novaVersao, origem, origemId, representacao, hash,
				timestamp);
		return new VersaoRegra(id, novaVersao, origem, agora);
	}

	private int proximaVersao(UUID jobId) {
		Integer maior = this.repository.buscarMaiorVersao(jobId);
		return ((maior != null) ? maior : 0) + 1;
	}

	record VersaoRegra(UUID id, int versao, String origem, Instant criadaEm) {
	}

}
