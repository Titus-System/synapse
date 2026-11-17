package synapse.api.auditoria;

import java.util.UUID;
import java.util.regex.Pattern;

import org.jspecify.annotations.Nullable;

record ConsultaEventosAuditoria(@Nullable String usuario, @Nullable String mes, @Nullable String loja,
		@Nullable String marca, @Nullable String cargo, @Nullable String regra) {

	private static final Pattern MES = Pattern.compile("^[0-9]{4}-(0[1-9]|1[0-2])$");

	private static final Pattern UUID_CANONICO = Pattern
		.compile("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$");

	ConsultaEventosAuditoria {
		validarTexto(usuario, "usuario");
		validarTexto(loja, "loja");
		validarTexto(marca, "marca");
		validarTexto(cargo, "cargo");
		validarTexto(regra, "regra");
		if (mes != null && !MES.matcher(mes).matches()) {
			throw RequisicaoInvalidaNaAuditoriaException.mes();
		}
	}

	@Nullable UUID jobId() {
		return this.regra != null && UUID_CANONICO.matcher(this.regra).matches() ? UUID.fromString(this.regra) : null;
	}

	@Nullable String nomePadrao() {
		if (this.regra == null || jobId() != null) {
			return null;
		}
		return "%" + this.regra.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%";
	}

	private static void validarTexto(@Nullable String valor, String parametro) {
		if (valor != null && (valor.isEmpty() || valor.indexOf('\0') >= 0)) {
			throw RequisicaoInvalidaNaAuditoriaException.filtro(parametro);
		}
	}

}
