package synapse.api.job;

import java.util.Set;
import java.util.stream.Collectors;

import org.springframework.http.HttpStatus;

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
