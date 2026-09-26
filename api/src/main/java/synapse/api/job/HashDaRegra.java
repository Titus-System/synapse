package synapse.api.job;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Objects;

import tools.jackson.core.StreamWriteFeature;
import tools.jackson.databind.MapperFeature;
import tools.jackson.databind.cfg.JsonNodeFeature;
import tools.jackson.databind.json.JsonMapper;

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
