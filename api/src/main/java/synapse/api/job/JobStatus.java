package synapse.api.job;

import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * Os nove estados do job e as transições permitidas entre eles - o único lugar do código
 * que os declara. {@code simulacao_inviavel} não tem aresta direta para {@code liberado}:
 * o único predecessor de {@code liberado} é {@code aguardando_decisao_usuario},
 * alcançável apenas por uma simulação concluída ({@code simulando}). Uma nova tentativa
 * após adaptação da regra volta a {@code gerando_regra} e precisa passar de novo por uma
 * simulação; não há atalho.
 */
public enum JobStatus {

	AGUARDANDO_CONFIRMACAO_PARAMETROS, GERANDO_REGRA, SIMULANDO, SIMULACAO_INVIAVEL, AGUARDANDO_DECISAO_USUARIO,
	LIBERADO, CANCELADO, ARQUIVADO, ERRO;

	private static final Map<JobStatus, Set<JobStatus>> TRANSICOES_PERMITIDAS = Map.of(

			AGUARDANDO_CONFIRMACAO_PARAMETROS, Set.of(GERANDO_REGRA, CANCELADO),

			GERANDO_REGRA, Set.of(SIMULANDO, ERRO),

			SIMULANDO, Set.of(AGUARDANDO_DECISAO_USUARIO, SIMULACAO_INVIAVEL, ERRO),

			SIMULACAO_INVIAVEL, Set.of(GERANDO_REGRA, AGUARDANDO_CONFIRMACAO_PARAMETROS, CANCELADO, ARQUIVADO),

			AGUARDANDO_DECISAO_USUARIO, Set.of(LIBERADO, CANCELADO, ARQUIVADO),

			LIBERADO, Set.of(),

			CANCELADO, Set.of(),

			ARQUIVADO, Set.of(),

			ERRO, Set.of());

	public boolean permiteTransicaoPara(JobStatus destino) {
		return TRANSICOES_PERMITIDAS.getOrDefault(this, Set.of()).contains(destino);
	}

	public boolean terminal() {
		return TRANSICOES_PERMITIDAS.getOrDefault(this, Set.of()).isEmpty();
	}

	public String paraColuna() {
		return name().toLowerCase(Locale.ROOT);
	}

	public static JobStatus deColuna(String valor) {
		return JobStatus.valueOf(valor.toUpperCase(Locale.ROOT));
	}

}
