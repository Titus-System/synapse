package synapse.api.job;

import java.util.Arrays;
import java.util.Locale;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.jspecify.annotations.Nullable;

/**
 * Os nós do grafo do codegen, no mesmo vocabulário fechado de
 * {@code comum.schema.json#/$defs/no_grafo}. Único lugar da api que os declara.
 * {@code SUGESTAO_ADAPTACAO} é o desvio acionado pela decisão quando a simulação é
 * inviável por orçamento; os demais são a sequência de 1 a 8.
 */
enum EtapaDoGrafo {

	EXTRACAO_PARAMETROS, VALIDACAO_DOMINIO, CONFIRMACAO, GERACAO_CODIGO, DELEGACAO_WORKER, INTERPRETACAO_RESULTADO,
	DECISAO, SUGESTAO_ADAPTACAO, EXPLICACAO;

	private static final Map<String, EtapaDoGrafo> POR_NOME_DE_EVENTO = Arrays.stream(values())
		.collect(Collectors.toMap(EtapaDoGrafo::paraEvento, Function.identity()));

	String paraEvento() {
		return name().toLowerCase(Locale.ROOT);
	}

	/**
	 * {@code null} quando {@code nome} não é um nó conhecido do grafo - uma etapa nova,
	 * ainda não implantada nesta api, ou um payload corrompido. A ausência é o próprio
	 * sinal para quem chama: não há exceção aqui, porque lançar dentro de um consumidor
	 * de fila viraria requeue infinito.
	 */
	static @Nullable EtapaDoGrafo deEvento(@Nullable String nome) {
		return (nome != null) ? POR_NOME_DE_EVENTO.get(nome) : null;
	}

}
