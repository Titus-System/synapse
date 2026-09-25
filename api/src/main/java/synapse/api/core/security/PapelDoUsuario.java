package synapse.api.core.security;

import org.springframework.security.access.AccessDeniedException;

public enum PapelDoUsuario {

	PROFISSIONAL_RH("profissional_rh"), AUDITOR("auditor");

	private final String coluna;

	PapelDoUsuario(String coluna) {
		this.coluna = coluna;
	}

	public String paraColuna() {
		return this.coluna;
	}

	public static PapelDoUsuario deColuna(String papel) {
		return switch (papel) {
			case "profissional_rh" -> PROFISSIONAL_RH;
			case "auditor" -> AUDITOR;
			default -> throw new AccessDeniedException("Papel não reconhecido.");
		};
	}

}
