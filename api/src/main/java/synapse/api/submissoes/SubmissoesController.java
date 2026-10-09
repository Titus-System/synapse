package synapse.api.submissoes;

import java.io.IOException;

import jakarta.servlet.http.HttpServletRequest;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.UsuarioAtual;

@RestController
class SubmissoesController {

	private final SubmissoesService service;

	private final UsuarioAtual usuario;

	private final CorrelationContext correlacao;

	SubmissoesController(SubmissoesService service, UsuarioAtual usuario, CorrelationContext correlacao) {
		this.service = service;
		this.usuario = usuario;
		this.correlacao = correlacao;
	}

	@PostMapping(path = "/submissoes", consumes = "application/json", produces = "application/json")
	@ResponseStatus(HttpStatus.CREATED)
	SubmissaoCriada texto(@RequestBody String corpo, HttpServletRequest request) {
		var acesso = this.usuario.obter();
		request.setAttribute("submissao.usuario", acesso.usuarioId().toString());
		try (var escopo = this.correlacao.abrir(null, acesso.usuarioId().toString())) {
			var resposta = this.service.texto(EntradaSubmissao.ler(corpo, "texto"), acesso);
			request.setAttribute("submissao.job", resposta.job().id().toString());
			return resposta;
		}
	}

	@PostMapping(path = "/submissoes", consumes = "multipart/form-data", produces = "application/json")
	@ResponseStatus(HttpStatus.CREATED)
	SubmissaoCriada voz(@RequestPart("audio") MultipartFile arquivo, @RequestPart("parametros") String parametros,
			HttpServletRequest request) throws IOException {
		var acesso = this.usuario.obter();
		request.setAttribute("submissao.usuario", acesso.usuarioId().toString());
		try (var escopo = this.correlacao.abrir(null, acesso.usuarioId().toString())) {
			var entrada = EntradaSubmissao.ler(parametros, "voz");
			var audio = AudioSubmissao.ler(arquivo);
			request.setAttribute("submissao.formato", audio.formato());
			request.setAttribute("submissao.faixa", audio.faixa());
			var resposta = this.service.voz(entrada, audio, acesso);
			request.setAttribute("submissao.job", resposta.job().id().toString());
			return resposta;
		}
	}

}
