package synapse.api.job;

import java.util.Locale;

enum EstadoRodada {

	PENDENTE, EM_TRANSCRICAO, EM_REEXTRACAO, REEXTRACAO_FALHOU, CORRIGIDA, ABANDONADA;

	String paraColuna() {
		return name().toLowerCase(Locale.ROOT);
	}

	static EstadoRodada deColuna(String valor) {
		return valueOf(valor.toUpperCase(Locale.ROOT));
	}

}
