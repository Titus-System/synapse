package synapse.api.job;

import java.util.Locale;

import org.jspecify.annotations.Nullable;

/**
 * A tabela de decisão de {@code simulacao-concluida}: para onde o job vai e por quê, a
 * partir do par {@code status} + {@code veredito} do evento. Único lugar da api que
 * traduz esses dois vocabulários fechados.
 *
 * <p>
 * {@code assercao_violada} leva a {@link JobStatus#ERRO}, não a
 * {@link JobStatus#SIMULACAO_INVIAVEL}: o código rodou e produziu números, mas uma
 * invariante foi violada e o número não vale. Inviabilidade é um veredito sobre um número
 * confiável; asserção violada é a ausência dele.
 */
enum DesfechoDaSimulacao {

	VIAVEL(JobStatus.AGUARDANDO_DECISAO_USUARIO, null),

	INDETERMINADO(JobStatus.AGUARDANDO_DECISAO_USUARIO, null),

	INVIAVEL(JobStatus.SIMULACAO_INVIAVEL, "Orçamento do período não comporta a regra proposta."),

	ASSERCAO_VIOLADA(JobStatus.ERRO, "Asserção invariante violada na execução; o número apurado não é confiável."),

	ERRO_CODIGO(JobStatus.ERRO, "Falha na execução do código gerado."),

	ERRO_INFRA(JobStatus.ERRO, "Falha de infraestrutura durante a execução.");

	private final JobStatus destino;

	private final @Nullable String razao;

	DesfechoDaSimulacao(JobStatus destino, @Nullable String razao) {
		this.destino = destino;
		this.razao = razao;
	}

	JobStatus destino() {
		return this.destino;
	}

	/**
	 * O que vai para {@code job_transicoes.motivo}: o token do vocabulário do evento, e
	 * não a razão localizada, porque é por ele que {@code erro_codigo} e
	 * {@code erro_infra} ficam distinguíveis para quem decide sobre retry automático.
	 * {@code null} fora de uma parada.
	 */
	@Nullable String motivoDaTrilha() {
		return (this.razao != null) ? name().toLowerCase(Locale.ROOT) : null;
	}

	/**
	 * O que vai para o campo {@code motivo} do evento SSE {@code estado}: a razão
	 * localizada da parada, como o contrato HTTP a descreve. {@code null} fora de uma
	 * parada.
	 */
	@Nullable String razaoLocalizada() {
		return this.razao;
	}

	/**
	 * {@code null} quando o par recebido não descreve um desfecho conhecido - status fora
	 * do vocabulário, ou {@code sucesso} sem um veredito que o sustente. A ausência é o
	 * próprio sinal para quem chama: não há exceção aqui, porque lançar dentro de um
	 * consumidor de fila viraria requeue infinito.
	 */
	static @Nullable DesfechoDaSimulacao de(@Nullable String status, @Nullable String veredito) {
		if (status == null) {
			return null;
		}
		return switch (status) {
			case "sucesso" -> peloVeredito(veredito);
			case "assercao_violada" -> ASSERCAO_VIOLADA;
			case "erro_codigo" -> ERRO_CODIGO;
			case "erro_infra" -> ERRO_INFRA;
			default -> null;
		};
	}

	/**
	 * O veredito só é lido na origem {@code sucesso}: o schema o declara ausente nos
	 * demais status, porque aí não há número que o sustente.
	 */
	private static @Nullable DesfechoDaSimulacao peloVeredito(@Nullable String veredito) {
		if (veredito == null) {
			return null;
		}
		return switch (veredito) {
			case "viavel" -> VIAVEL;
			case "inviavel" -> INVIAVEL;
			case "indeterminado" -> INDETERMINADO;
			default -> null;
		};
	}

}
