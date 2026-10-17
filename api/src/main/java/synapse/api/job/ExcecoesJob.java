package synapse.api.job;

import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

import org.springframework.http.HttpStatus;

class FalhaPersistenciaEtapaException extends RuntimeException {

	FalhaPersistenciaEtapaException() {
		// O container registra a cadeia inteira; não retenha a exceção com artefatos.
		super("falha de persistência ao consumir etapa-alterada", null, false, true);
	}

}

class CriarJobException extends RuntimeException {

	private final HttpStatus status;

	private final ErroCriarJobDto erro;

	private CriarJobException(HttpStatus status, String codigo, String mensagem, List<ElementoErroDto> elementos) {
		super(mensagem);
		this.status = status;
		this.erro = new ErroCriarJobDto(codigo, mensagem, elementos);
	}

	static CriarJobException requisicao(String mensagem) {
		return new CriarJobException(HttpStatus.BAD_REQUEST, "requisicao_invalida", mensagem, List.of());
	}

	static CriarJobException nucleoIncompleto(List<ElementoErroDto> elementos) {
		return new CriarJobException(HttpStatus.UNPROCESSABLE_CONTENT, "nucleo_incompleto",
				"Preencha os campos obrigatórios do núcleo da regra.", elementos);
	}

	static CriarJobException campoInvalido(String campo, String motivo) {
		return new CriarJobException(HttpStatus.BAD_REQUEST, "requisicao_invalida", motivo,
				List.of(new ElementoErroDto("nucleo." + campo, motivo)));
	}

	static CriarJobException semUsuarioAtivo() {
		return new CriarJobException(HttpStatus.SERVICE_UNAVAILABLE, "usuario_ativo_indisponivel",
				"Nenhum usuário ativo disponível para criar o job.", List.of());
	}

	HttpStatus status() {
		return this.status;
	}

	ErroCriarJobDto erro() {
		return this.erro;
	}

}

class ConfirmarParametrosException extends RuntimeException {

	private final HttpStatus status;

	private final ErroCriarJobDto erro;

	private ConfirmarParametrosException(HttpStatus status, String codigo, String mensagem,
			List<ElementoErroDto> elementos) {
		super(mensagem);
		this.status = status;
		this.erro = new ErroCriarJobDto(codigo, mensagem, elementos);
	}

	static ConfirmarParametrosException requisicao(String mensagem) {
		return new ConfirmarParametrosException(HttpStatus.BAD_REQUEST, "requisicao_invalida", mensagem, List.of());
	}

	static ConfirmarParametrosException nucleoIncompleto(List<ElementoErroDto> elementos) {
		return new ConfirmarParametrosException(HttpStatus.UNPROCESSABLE_CONTENT, "nucleo_incompleto",
				"Preencha os campos obrigatórios do núcleo da regra.", elementos);
	}

	static ConfirmarParametrosException campoInvalido(String campo, String motivo) {
		return new ConfirmarParametrosException(HttpStatus.BAD_REQUEST, "requisicao_invalida", motivo,
				List.of(new ElementoErroDto("nucleo." + campo, motivo)));
	}

	static ConfirmarParametrosException estadoInvalido() {
		return new ConfirmarParametrosException(HttpStatus.CONFLICT, "estado_invalido",
				"Este job não está aguardando confirmação de parâmetros.", List.of());
	}

	static ConfirmarParametrosException versaoJaAnalisada() {
		return new ConfirmarParametrosException(HttpStatus.CONFLICT, "estado_invalido",
				"Esta versão já foi analisada. Altere a regra ou os parâmetros antes de confirmar.", List.of());
	}

	HttpStatus status() {
		return this.status;
	}

	ErroCriarJobDto erro() {
		return this.erro;
	}

}

class ExecutarAcaoException extends RuntimeException {

	private final HttpStatus status;

	private final ErroDto erro;

	private ExecutarAcaoException(HttpStatus status, String codigo, String mensagem) {
		super(mensagem);
		this.status = status;
		this.erro = new ErroDto(codigo, mensagem);
	}

	static ExecutarAcaoException requisicao(String mensagem) {
		return new ExecutarAcaoException(HttpStatus.BAD_REQUEST, "requisicao_invalida", mensagem);
	}

	static ExecutarAcaoException simulacaoInviavel() {
		return new ExecutarAcaoException(HttpStatus.CONFLICT, "simulacao_inviavel",
				"A simulação excede o orçamento informado e a regra não pode ser liberada para produção.");
	}

	static ExecutarAcaoException estadoInvalido(AcaoJob acao, JobStatus origem) {
		if (acao == AcaoJob.ACEITAR_META) {
			return new ExecutarAcaoException(HttpStatus.CONFLICT, "estado_invalido",
					"A ação aceitar_meta exige uma meta sugerida pendente e o job aguardando a decisão do usuário.");
		}
		Set<JobStatus> origensPermitidas = JobStatus.origensPermitidasPara(acao.destino());
		String estados = origensPermitidas.stream()
			.map(JobStatus::paraColuna)
			.sorted()
			.collect(Collectors.joining(", "));
		String mensagem = "A ação %s exige o job em %s; o job está em %s.".formatted(acao.paraColuna(), estados,
				origem.paraColuna());
		return new ExecutarAcaoException(HttpStatus.CONFLICT, "estado_invalido", mensagem);
	}

	HttpStatus status() {
		return this.status;
	}

	ErroDto erro() {
		return this.erro;
	}

}

/** Parâmetro de paginação de {@code GET /jobs} fora do que o contrato aceita. */
class ListarJobsException extends RuntimeException {

	private final String mensagem;

	private ListarJobsException(String mensagem) {
		super(mensagem);
		this.mensagem = mensagem;
	}

	static ListarJobsException pagina() {
		return new ListarJobsException("O parâmetro pagina precisa ser um inteiro maior ou igual a zero.");
	}

	static ListarJobsException tamanho() {
		return new ListarJobsException("O parâmetro tamanho precisa ser um inteiro entre 1 e 100.");
	}

	String mensagem() {
		return this.mensagem;
	}

}

class ReprocessarJobException extends RuntimeException {

	private final HttpStatus status;

	private final ErroDto erro;

	private ReprocessarJobException(HttpStatus status, String codigo, String mensagem) {
		super(mensagem);
		this.status = status;
		this.erro = new ErroDto(codigo, mensagem);
	}

	static ReprocessarJobException requisicao(String mensagem) {
		return new ReprocessarJobException(HttpStatus.BAD_REQUEST, "requisicao_invalida", mensagem);
	}

	static ReprocessarJobException estadoInvalido() {
		return new ReprocessarJobException(HttpStatus.CONFLICT, "estado_invalido",
				"Somente um job arquivado pode ser reprocessado.");
	}

	static ReprocessarJobException semRegra() {
		return new ReprocessarJobException(HttpStatus.CONFLICT, "estado_invalido",
				"O job arquivado não possui uma regra formada para reprocessamento.");
	}

	HttpStatus status() {
		return this.status;
	}

	ErroDto erro() {
		return this.erro;
	}

}

/** Não existe job com o identificador informado. */
class JobNaoEncontradoException extends RuntimeException {

	JobNaoEncontradoException(UUID jobId) {
		super("Job não encontrado: " + jobId);
	}

}

/** A simulação não existe ou pertence a outro job. */
class SimulacaoNaoEncontradaException extends RuntimeException {

	SimulacaoNaoEncontradaException(UUID simulacaoId) {
		super("Simulação não encontrada: " + simulacaoId);
	}

}

/**
 * Recusa de PUT /jobs/{id}/nome. O motivo vai para o log; a resposta é sempre
 * requisicao_invalida.
 */
class RenomearJobException extends RuntimeException {

	enum Motivo {

		NOME_AUSENTE, NOME_VAZIO, NOME_MUITO_LONGO;

		String paraLog() {
			return name().toLowerCase(Locale.ROOT);
		}

	}

	private final Motivo motivo;

	private final ErroDto erro;

	private RenomearJobException(Motivo motivo, String mensagem) {
		super(mensagem);
		this.motivo = motivo;
		this.erro = new ErroDto("requisicao_invalida", mensagem);
	}

	static RenomearJobException requisicao(Motivo motivo, String mensagem) {
		return new RenomearJobException(motivo, mensagem);
	}

	HttpStatus status() {
		return HttpStatus.BAD_REQUEST;
	}

	Motivo motivo() {
		return this.motivo;
	}

	ErroDto erro() {
		return this.erro;
	}

}

/** A sessão é válida, mas não pode acessar o job solicitado. */
class SemPermissaoNoJobException extends RuntimeException {

}
