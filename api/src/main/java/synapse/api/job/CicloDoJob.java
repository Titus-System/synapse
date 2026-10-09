package synapse.api.job;

import java.util.Arrays;
import java.util.Locale;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.jspecify.annotations.Nullable;

/**
 * As quatro ações de finalização do contrato HTTP ({@code AcaoJob}), no mesmo vocabulário
 * da coluna {@code job_acoes.acao}. {@code SALVAR} é sinônimo de
 * {@code CONFIRMAR_LIBERAR}: não existe estado "salvo" na máquina de estados, e as duas
 * levam a {@link JobStatus#LIBERADO} sob a mesma recusa quando a simulação é inviável.
 */
enum AcaoJob {

	CONFIRMAR_LIBERAR(JobStatus.LIBERADO), CANCELAR(JobStatus.CANCELADO), SALVAR(JobStatus.LIBERADO),
	ARQUIVAR(JobStatus.ARQUIVADO);

	private final JobStatus destino;

	AcaoJob(JobStatus destino) {
		this.destino = destino;
	}

	JobStatus destino() {
		return this.destino;
	}

	String paraColuna() {
		return name().toLowerCase(Locale.ROOT);
	}

	static AcaoJob deColuna(String valor) {
		return AcaoJob.valueOf(valor.toUpperCase(Locale.ROOT));
	}

}

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
	 * O inverso de {@link #motivoDaTrilha()}: o desfecho cujo token foi gravado em
	 * {@code job_transicoes.motivo}. {@code null} para um token que não é de desfecho,
	 * como os de falha anterior à simulação ou de transição sem parada.
	 */
	static @Nullable DesfechoDaSimulacao peloMotivoDaTrilha(String motivo) {
		for (DesfechoDaSimulacao desfecho : values()) {
			if (motivo.equals(desfecho.motivoDaTrilha())) {
				return desfecho;
			}
		}
		return null;
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

/**
 * Único tradutor do token gravado em {@code job_transicoes.motivo} para a razão
 * localizada que o usuário lê, tanto no evento SSE {@code estado} quanto em {@code GET
 * /jobs/{id}}. A trilha guarda o token, e não a razão, porque é por ele que as falhas
 * ficam distinguíveis para a decisão operacional; a tradução só acontece na saída.
 */
final class MotivoDaParada {

	static final String FALHA_ANTES_DA_SIMULACAO = "Falha durante o processamento da regra, antes da simulação.";

	/** O token de {@code job_transicoes.motivo} de uma transcrição de voz que falhou. */
	static final String FALHA_NA_TRANSCRICAO = "erro_transcricao";

	static final String TRANSCRICAO_FALHOU = "Não foi possível transcrever a gravação. Envie a regra de novo, por texto ou por voz.";

	private static final String PREFIXO_FALHA_NA_ETAPA = "erro_";

	private MotivoDaParada() {
	}

	/** O token de {@code job_transicoes.motivo} de uma falha anterior à simulação. */
	static String falhaNaEtapa(EtapaDoGrafo etapa) {
		return PREFIXO_FALHA_NA_ETAPA + etapa.paraEvento();
	}

	/**
	 * A razão da parada que levou o job a {@code status}, ou {@code null} quando o token
	 * não descreve uma parada que termina nesse status: sem token, token de transição sem
	 * parada ({@code sugestao_adaptacao_proposta}), token desconhecido ou token de uma
	 * parada que leva a outro estado. É o destino que impede uma causa antiga de ser lida
	 * como o motivo do estado corrente.
	 */
	static @Nullable String razaoLocalizada(JobStatus status, @Nullable String motivoDaTrilha) {
		if (motivoDaTrilha == null) {
			return null;
		}
		DesfechoDaSimulacao desfecho = DesfechoDaSimulacao.peloMotivoDaTrilha(motivoDaTrilha);
		if (desfecho != null) {
			return (desfecho.destino() == status) ? desfecho.razaoLocalizada() : null;
		}
		if (status == JobStatus.ERRO && FALHA_NA_TRANSCRICAO.equals(motivoDaTrilha)) {
			return TRANSCRICAO_FALHOU;
		}
		if (status == JobStatus.ERRO && motivoDaTrilha.startsWith(PREFIXO_FALHA_NA_ETAPA)
				&& EtapaDoGrafo.deEvento(motivoDaTrilha.substring(PREFIXO_FALHA_NA_ETAPA.length())) != null) {
			return FALHA_ANTES_DA_SIMULACAO;
		}
		return null;
	}

}
