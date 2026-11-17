package synapse.api.auditoria;

import java.util.UUID;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RestController;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.AcessoDoUsuario;

/**
 * O resumo do dossiê de um job para o auditor. O acesso já foi decidido por
 * {@link AcessoAuditoriaInterceptor}. O log leva o desfecho, nunca os valores da regra ou
 * dos resultados.
 */
@RestController
class ResumoAuditoriaController {

	private static final Logger log = LoggerFactory.getLogger(ResumoAuditoriaController.class);

	private final ResumoAuditoriaService service;

	private final CorrelationContext correlacao;

	ResumoAuditoriaController(ResumoAuditoriaService service, CorrelationContext correlacao) {
		this.service = service;
		this.correlacao = correlacao;
	}

	@GetMapping(path = "/auditoria/jobs/{id}/resumo", produces = "application/json")
	ResumoDossieAuditoriaDto consultarResumo(@PathVariable UUID id,
			@RequestAttribute(AcessoAuditoriaInterceptor.ACESSO) AcessoDoUsuario acesso) {
		try (var escopo = this.correlacao.abrir(id.toString(), acesso.usuarioId().toString())) {
			long inicio = System.nanoTime();
			String resultado = "falha";
			try {
				ResumoDossieAuditoriaDto resumo = this.service.consultar(id);
				resultado = "sucesso";
				return resumo;
			}
			catch (JobNaoEncontradoNaAuditoriaException ex) {
				resultado = "job_nao_encontrado";
				throw ex;
			}
			finally {
				log.atLevel(nivel(resultado))
					.addKeyValue("operacao", "consultar_resumo_auditoria")
					.addKeyValue("resultado", resultado)
					.addKeyValue("duracao_ms", TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - inicio))
					.log("consulta de resumo de auditoria encerrada");
			}
		}
	}

	private static Level nivel(String resultado) {
		return switch (resultado) {
			case "sucesso" -> Level.INFO;
			case "falha" -> Level.ERROR;
			default -> Level.WARN;
		};
	}

}
