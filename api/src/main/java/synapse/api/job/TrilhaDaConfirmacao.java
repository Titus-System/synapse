package synapse.api.job;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.jspecify.annotations.Nullable;
import tools.jackson.databind.JsonNode;
import synapse.api.job.JobRepository.VersaoAnterior;

final class TrilhaDaConfirmacao {

	private TrilhaDaConfirmacao() {
	}

	static void registrar(JobRepository repository, UUID jobId, UUID regraId, boolean editado,
			RepresentacaoRegraDto atual, @Nullable VersaoAnterior anterior, List<String> parametrosCorrigidos,
			Timestamp timestamp) {
		List<String> corrigidos = (anterior != null && editado) ? camposCorrigidos(atual.nucleo(), anterior.nucleo())
				: new ArrayList<>();
		if (anterior != null && editado) {
			corrigidos.addAll(especificacoesCorrigidas(atual.especificacoes(), anterior.especificacoes()));
		}
		corrigidos.addAll(parametrosCorrigidos);
		String resumo = editado ? "usuário corrigiu "
				+ (corrigidos.isEmpty() ? "a representação" : String.join(", ", corrigidos)) + " antes de confirmar"
				: "usuário confirmou os parâmetros";
		Map<String, Object> conclusao = new LinkedHashMap<>();
		conclusao.put("resumo", resumo);
		conclusao.put("editado_pelo_usuario", editado);
		conclusao.put("campos_corrigidos", corrigidos);
		UUID eventoId = UUID.nameUUIDFromBytes(("confirmacao:" + regraId).getBytes(StandardCharsets.UTF_8));
		repository.inserirTrilhaConfirmacao(eventoId, jobId, timestamp, regraId, conclusao);
	}

	private static List<String> camposCorrigidos(NucleoRegraDto atual, NucleoRegraDto anterior) {
		List<String> corrigidos = new ArrayList<>();
		if (!Objects.equals(atual.vigencia(), anterior.vigencia())) {
			corrigidos.add("nucleo.vigencia");
		}
		if (!Objects.equals(atual.loja(), anterior.loja())) {
			corrigidos.add("nucleo.loja");
		}
		if (!Objects.equals(atual.marca(), anterior.marca())) {
			corrigidos.add("nucleo.marca");
		}
		if (!Objects.equals(atual.cargo(), anterior.cargo())) {
			corrigidos.add("nucleo.cargo");
		}
		if (decimalDiferente(atual.percentual(), anterior.percentual())) {
			corrigidos.add("nucleo.percentual");
		}
		return corrigidos;
	}

	static boolean decimalDiferente(@Nullable BigDecimal atual, @Nullable BigDecimal anterior) {
		if (atual == null || anterior == null) {
			return (atual == null) != (anterior == null);
		}
		return atual.compareTo(anterior) != 0;
	}

	private static List<String> especificacoesCorrigidas(List<JsonNode> atuais, List<JsonNode> anteriores) {
		var refs = new LinkedHashSet<String>();
		atuais.forEach(elemento -> refs.add(elemento.path("ref").asString()));
		anteriores.forEach(elemento -> refs.add(elemento.path("ref").asString()));
		return refs.stream()
			.filter(ref -> !atuais.stream()
				.filter(elemento -> ref.equals(elemento.path("ref").asString()))
				.toList()
				.equals(anteriores.stream().filter(elemento -> ref.equals(elemento.path("ref").asString())).toList()))
			.toList();
	}

}
