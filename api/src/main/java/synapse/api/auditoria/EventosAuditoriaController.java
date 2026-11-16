package synapse.api.auditoria;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.security.AcessoDoUsuario;

@RestController
class EventosAuditoriaController {

	private static final Logger log = LoggerFactory.getLogger(EventosAuditoriaController.class);

	private final EventosAuditoriaService service;

	private final CorrelationContext correlacao;

	EventosAuditoriaController(EventosAuditoriaService service, CorrelationContext correlacao) {
		this.service = service;
		this.correlacao = correlacao;
	}

	@GetMapping(path = "/auditoria/eventos", produces = "application/json")
	PaginaEventosAuditoriaDto listar(@RequestParam(name = "pagina", defaultValue = "0") String pagina,
			@RequestParam(name = "tamanho", defaultValue = "20") String tamanho,
			@RequestParam(name = "usuario", required = false) @Nullable String usuario,
			@RequestParam(name = "mes", required = false) @Nullable String mes,
			@RequestParam(name = "loja", required = false) @Nullable String loja,
			@RequestParam(name = "marca", required = false) @Nullable String marca,
			@RequestParam(name = "cargo", required = false) @Nullable String cargo,
			@RequestParam(name = "regra", required = false) @Nullable String regra,
			@RequestAttribute(AcessoAuditoriaInterceptor.ACESSO) AcessoDoUsuario acesso) {
		try (var escopo = this.correlacao.abrir(null, acesso.usuarioId().toString())) {
			long inicio = System.nanoTime();
			String resultado = "falha";
			Integer numeroPagina = null;
			Integer numeroTamanho = null;
			Long total = null;
			try {
				numeroPagina = inteiro(pagina, true);
				numeroTamanho = inteiro(tamanho, false);
				PaginaAuditoria paginacao = new PaginaAuditoria(numeroPagina, numeroTamanho);
				ConsultaEventosAuditoria consulta = new ConsultaEventosAuditoria(usuario, mes, loja, marca, cargo,
						regra);
				PaginaEventosAuditoriaDto resposta = this.service.listar(consulta, paginacao);
				total = resposta.total();
				resultado = "sucesso";
				return resposta;
			}
			catch (RequisicaoInvalidaNaAuditoriaException ex) {
				resultado = "requisicao_invalida";
				throw ex;
			}
			finally {
				log.atLevel(nivel(resultado))
					.addKeyValue("operacao", "listar_eventos_auditoria")
					.addKeyValue("resultado", resultado)
					.addKeyValue("filtros_preenchidos", preenchidos(usuario, mes, loja, marca, cargo, regra))
					.addKeyValue("pagina", numeroPagina)
					.addKeyValue("tamanho", numeroTamanho)
					.addKeyValue("total", total)
					.addKeyValue("duracao_ms", TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - inicio))
					.log("consulta de eventos de auditoria encerrada");
			}
		}
	}

	@GetMapping(path = "/auditoria/eventos/filtros", produces = "application/json")
	FiltrosEventosAuditoriaDto consultarFiltros(
			@RequestAttribute(AcessoAuditoriaInterceptor.ACESSO) AcessoDoUsuario acesso) {
		try (var escopo = this.correlacao.abrir(null, acesso.usuarioId().toString())) {
			long inicio = System.nanoTime();
			String resultado = "falha";
			Long total = null;
			try {
				FiltrosEventosAuditoriaDto resposta = this.service.consultarFiltros();
				total = (long) resposta.usuarios().size() + resposta.meses().size() + resposta.lojas().size()
						+ resposta.marcas().size() + resposta.cargos().size();
				resultado = "sucesso";
				return resposta;
			}
			finally {
				log.atLevel(nivel(resultado))
					.addKeyValue("operacao", "consultar_filtros_eventos_auditoria")
					.addKeyValue("resultado", resultado)
					.addKeyValue("total", total)
					.addKeyValue("duracao_ms", TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - inicio))
					.log("consulta de filtros de auditoria encerrada");
			}
		}
	}

	private static int inteiro(String valor, boolean pagina) {
		try {
			return Integer.parseInt(valor);
		}
		catch (NumberFormatException ex) {
			throw pagina ? RequisicaoInvalidaNaAuditoriaException.pagina()
					: RequisicaoInvalidaNaAuditoriaException.tamanho();
		}
	}

	private static List<String> preenchidos(@Nullable String usuario, @Nullable String mes, @Nullable String loja,
			@Nullable String marca, @Nullable String cargo, @Nullable String regra) {
		List<String> filtros = new ArrayList<>();
		adicionarPreenchido(filtros, "usuario", usuario);
		adicionarPreenchido(filtros, "mes", mes);
		adicionarPreenchido(filtros, "loja", loja);
		adicionarPreenchido(filtros, "marca", marca);
		adicionarPreenchido(filtros, "cargo", cargo);
		adicionarPreenchido(filtros, "regra", regra);
		return List.copyOf(filtros);
	}

	private static void adicionarPreenchido(List<String> filtros, String nome, @Nullable String valor) {
		if (valor != null && !valor.isEmpty()) {
			filtros.add(nome);
		}
	}

	private static Level nivel(String resultado) {
		return switch (resultado) {
			case "sucesso" -> Level.INFO;
			case "requisicao_invalida" -> Level.WARN;
			default -> Level.ERROR;
		};
	}

}
