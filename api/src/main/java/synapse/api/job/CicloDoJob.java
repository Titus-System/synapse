package synapse.api.job;

import java.math.BigDecimal;
import java.util.Arrays;
import java.util.Locale;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.jspecify.annotations.Nullable;

import synapse.api.job.JobRepository.ComissaoForaDaRegra;

/**
 * As ações do contrato HTTP ({@code AcaoJob}), no mesmo vocabulário da coluna
 * {@code job_acoes.acao}. {@code SALVAR} é sinônimo de {@code CONFIRMAR_LIBERAR}: não
 * existe estado "salvo" na máquina de estados, e as duas levam a
 * {@link JobStatus#LIBERADO} sob a mesma recusa quando a simulação é inviável. Um
 * resultado sem orçamento não tem veredito e não é recusado. {@code ACEITAR_META} mantém
 * o job aguardando decisão: troca somente o resultado vigente, sem transição.
 */
enum AcaoJob {

	CONFIRMAR_LIBERAR(JobStatus.LIBERADO), CANCELAR(JobStatus.CANCELADO), SALVAR(JobStatus.LIBERADO),
	ARQUIVAR(JobStatus.ARQUIVADO), ACEITAR_META(JobStatus.AGUARDANDO_DECISAO_USUARIO);

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
 * {@code sucesso} sem veredito é o resultado de um job sem orçamento: a simulação foi
 * feita sem a verificação de orçamento, o número vale e não há critério que o julgue. Vai
 * à decisão do usuário como uma regra viável, e por isso pode ser liberado e salvo.
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

	SEM_ORCAMENTO(JobStatus.AGUARDANDO_DECISAO_USUARIO, null),

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

	/** O valor da tag {@code desfecho} da métrica de consumo, de conjunto fechado. */
	String paraMetrica() {
		return name().toLowerCase(Locale.ROOT);
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
	 * A falha do código gerado, que o codegen corrige enquanto a versão não chega ao
	 * limite de {@link CorrecaoDoCodigo}. A de infraestrutura fica de fora: outro código
	 * não a resolve.
	 */
	boolean corrigivel() {
		return this == ERRO_CODIGO || this == ASSERCAO_VIOLADA;
	}

	/**
	 * {@code null} quando o par recebido não descreve um desfecho conhecido - status fora
	 * do vocabulário, ou {@code sucesso} com veredito fora do vocabulário. A ausência é o
	 * próprio sinal para quem chama: não há exceção aqui, porque lançar dentro de um
	 * consumidor de fila viraria requeue infinito.
	 */
	static @Nullable DesfechoDaSimulacao de(@Nullable String status, @Nullable String veredito) {
		if (status == null) {
			return null;
		}
		return switch (status) {
			case "sucesso" -> (veredito == null) ? SEM_ORCAMENTO : peloVeredito(veredito);
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
	private static @Nullable DesfechoDaSimulacao peloVeredito(String veredito) {
		return switch (veredito) {
			case "viavel" -> VIAVEL;
			case "inviavel" -> INVIAVEL;
			case "indeterminado" -> INDETERMINADO;
			default -> null;
		};
	}

}

/**
 * A correção do código gerado cuja execução falhou: a falha volta ao modelo com o código,
 * e o código corrigido é executado de novo. Cada versão da regra tem no máximo
 * {@link #LIMITE_DE_CODIGOS_POR_VERSAO} códigos, contados pela ordem de criação em
 * {@code codigos_gerados}. O codegen aplica o mesmo limite pela mesma conta
 * ({@code codegen/app/correcao_codigo.py}), e por isso os dois chegam à mesma decisão em
 * qualquer ordem de consumo de {@code simulacao-concluida}.
 */
final class CorrecaoDoCodigo {

	static final int LIMITE_DE_CODIGOS_POR_VERSAO = 3;

	private CorrecaoDoCodigo() {
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

	static final String CAUSA_PROVEDOR_INDISPONIVEL = "provedor_indisponivel";

	static final String PROVEDOR_INDISPONIVEL = "O serviço de inteligência artificial ficou indisponível por muito tempo e a regra não foi processada. Envie a regra de novo mais tarde.";

	/**
	 * O token de {@code job_transicoes.motivo} do fim das tentativas de taxa nova sem uma
	 * que caiba no orçamento, anunciado pelo {@code sem_alternativa} do codegen.
	 */
	static final String SEM_ALTERNATIVA = "sem_alternativa";

	static final String NENHUMA_TAXA_COUBE = "Nenhuma das taxas de comissão testadas coube no orçamento do período.";

	private static final String PREFIXO_FALHA_NA_ETAPA = "erro_";

	private static final Locale PT_BR = Locale.of("pt", "BR");

	private static final String MOTIVO_DA_TRILHA_PROVEDOR_INDISPONIVEL = PREFIXO_FALHA_NA_ETAPA
			+ CAUSA_PROVEDOR_INDISPONIVEL;

	private MotivoDaParada() {
	}

	/**
	 * A razão do fim das tentativas de taxa nova sem alternativa. Quando as lojas fora da
	 * regra já custam mais que o orçamento, nenhuma taxa cabe e a razão diz isso, com os
	 * dois valores; sem esse piso, é a razão genérica.
	 */
	static String semAlternativa(@Nullable ComissaoForaDaRegra comissao) {
		if (comissao == null || comissao.fora().compareTo(comissao.orcamento()) <= 0) {
			return NENHUMA_TAXA_COUBE;
		}
		return "O orçamento de %s é menor que as comissões das lojas fora da regra (%s), que a sugestão não altera. Nenhuma redução de taxa faz a regra caber: aumente o orçamento ou revise o alcance da regra."
			.formatted(reais(comissao.orcamento()), reais(comissao.fora()));
	}

	private static String reais(BigDecimal valor) {
		return String.format(PT_BR, "R$ %,.2f", valor);
	}

	/** O token de {@code job_transicoes.motivo} de uma falha anterior à simulação. */
	static String falhaNaEtapa(EtapaDoGrafo etapa) {
		return PREFIXO_FALHA_NA_ETAPA + etapa.paraEvento();
	}

	/**
	 * O token de uma falha anterior à simulação com a {@code causa} do evento. A causa
	 * conhecida troca o token por um próprio, que não nomeia a etapa; sem causa, ou com
	 * uma causa que esta api não conhece, vale o token da etapa.
	 */
	static String falhaNaEtapa(EtapaDoGrafo etapa, @Nullable String causa) {
		return CAUSA_PROVEDOR_INDISPONIVEL.equals(causa) ? MOTIVO_DA_TRILHA_PROVEDOR_INDISPONIVEL : falhaNaEtapa(etapa);
	}

	/**
	 * A razão localizada de uma falha anterior à simulação, a mesma da consulta e do SSE.
	 */
	static String razaoDaFalha(@Nullable String causa) {
		return CAUSA_PROVEDOR_INDISPONIVEL.equals(causa) ? PROVEDOR_INDISPONIVEL : FALHA_ANTES_DA_SIMULACAO;
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
		if (status == JobStatus.SIMULACAO_INVIAVEL && SEM_ALTERNATIVA.equals(motivoDaTrilha)) {
			return NENHUMA_TAXA_COUBE;
		}
		// Os dois tokens próprios vêm antes do ramo da etapa: ambos começam com o mesmo
		// prefixo e nenhum nomeia um nó do grafo, então o ramo genérico não os alcança.
		if (status == JobStatus.ERRO && MOTIVO_DA_TRILHA_PROVEDOR_INDISPONIVEL.equals(motivoDaTrilha)) {
			return PROVEDOR_INDISPONIVEL;
		}
		if (status == JobStatus.ERRO && motivoDaTrilha.startsWith(PREFIXO_FALHA_NA_ETAPA)
				&& EtapaDoGrafo.deEvento(motivoDaTrilha.substring(PREFIXO_FALHA_NA_ETAPA.length())) != null) {
			return FALHA_ANTES_DA_SIMULACAO;
		}
		return null;
	}

}
