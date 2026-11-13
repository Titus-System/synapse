package synapse.api.auditoria;

import java.util.UUID;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.AcessoDoUsuario;

/**
 * Leitura investigativa dos jobs de qualquer dono. O acesso já foi decidido por
 * {@link AcessoAuditoriaInterceptor}. Os logs levam o desfecho e as referências, nunca o
 * conteúdo devolvido.
 */
@RestController
class AuditoriaController {

	private static final Logger log = LoggerFactory.getLogger(AuditoriaController.class);

	private final AuditoriaService service;

	private final CorrelationContext correlacao;

	AuditoriaController(AuditoriaService service, CorrelationContext correlacao) {
		this.service = service;
		this.correlacao = correlacao;
	}

	@GetMapping(path = "/auditoria/jobs", produces = "application/json")
	PaginaJobsAuditoriaDto listar(@RequestParam(name = "pagina", defaultValue = "0") int pagina,
			@RequestParam(name = "tamanho", defaultValue = "20") int tamanho,
			@RequestAttribute(AcessoAuditoriaInterceptor.ACESSO) AcessoDoUsuario acesso) {
		try (var escopo = this.correlacao.abrir(null, acesso.usuarioId().toString())) {
			long inicio = System.nanoTime();
			String resultado = "falha";
			try {
				PaginaJobsAuditoriaDto resposta = this.service.listar(new PaginaAuditoria(pagina, tamanho));
				resultado = "sucesso";
				return resposta;
			}
			catch (RequisicaoInvalidaNaAuditoriaException ex) {
				resultado = "requisicao_invalida";
				throw ex;
			}
			finally {
				log.atLevel(nivel(resultado))
					.addKeyValue("operacao", "listar_jobs_auditoria")
					.addKeyValue("resultado", resultado)
					.addKeyValue("pagina", pagina)
					.addKeyValue("tamanho", tamanho)
					.addKeyValue("duracao_ms", TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - inicio))
					.log("listagem de auditoria encerrada");
			}
		}
	}

	@GetMapping(path = "/auditoria/jobs/{id}", produces = "application/json")
	RegistroAuditoriaDto consultar(@PathVariable UUID id,
			@RequestAttribute(AcessoAuditoriaInterceptor.ACESSO) AcessoDoUsuario acesso) {
		try (var escopo = this.correlacao.abrir(id.toString(), acesso.usuarioId().toString())) {
			long inicio = System.nanoTime();
			String resultado = "falha";
			try {
				RegistroAuditoriaDto registro = this.service.consultar(id);
				resultado = "sucesso";
				return registro;
			}
			catch (JobNaoEncontradoNaAuditoriaException ex) {
				resultado = "job_nao_encontrado";
				throw ex;
			}
			finally {
				log.atLevel(nivel(resultado))
					.addKeyValue("operacao", "consultar_job_auditoria")
					.addKeyValue("resultado", resultado)
					.addKeyValue("duracao_ms", TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - inicio))
					.log("consulta de auditoria encerrada");
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
