package synapse.api.core.sse;

/**
 * Um evento a caminho de um cliente SSE. {@code nome} vai na linha {@code event:},
 * {@code dados} é serializado na linha {@code data:}. {@code ultimo} é semântica de
 * transporte: depois de entregue, o stream que o recebeu é fechado - quem decide isso é
 * quem produz o evento (a fatia de negócio), não {@link EmissoresSse}.
 */
public record EventoSse(String nome, Object dados, boolean ultimo) {

	public static EventoSse de(String nome, Object dados) {
		return new EventoSse(nome, dados, false);
	}

	public static EventoSse ultimo(String nome, Object dados) {
		return new EventoSse(nome, dados, true);
	}

}
