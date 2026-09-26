package synapse.api.core.sse;

import java.io.IOException;
import java.time.Duration;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import jakarta.servlet.AsyncEvent;
import jakarta.servlet.AsyncListener;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import org.springframework.mock.web.MockAsyncContext;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import synapse.api.core.logging.CorrelationContext;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;

/**
 * Unitário: exercita {@link EmissoresSse} através do ciclo real de um {@link SseEmitter}
 * sem subir servidor - o {@code MockMvc} processa a requisição e o retorno do controller
 * de teste do mesmo jeito que o Tomcat faria, e {@code MockAsyncContext} permite simular
 * o cliente sumindo (erro, timeout) sem uma conexão de rede de verdade. A confirmação de
 * ponta a ponta com HTTP real, incluindo o teste de vazamento com 100 conexões, está em
 * {@code AcompanharJobStreamTests}.
 */
class EmissoresSseTests {

	private EmissoresSse emissores;

	private MockMvc mockMvc;

	@BeforeEach
	void preparar() {
		this.emissores = new EmissoresSse(Duration.ofMinutes(1), new CorrelationContext());
		this.mockMvc = MockMvcBuilders.standaloneSetup(new StreamController(this.emissores)).build();
	}

	@RestController
	static class StreamController {

		private final EmissoresSse emissores;

		StreamController(EmissoresSse emissores) {
			this.emissores = emissores;
		}

		@GetMapping("/stream/{id}")
		SseEmitter stream(@PathVariable UUID id) {
			return this.emissores.inscrever(id, () -> EventoSse.de("estado", "fotografia"));
		}

		@GetMapping("/stream-terminal/{id}")
		SseEmitter streamTerminal(@PathVariable UUID id) {
			return this.emissores.inscrever(id, () -> EventoSse.ultimo("estado", "fotografia"));
		}

		@GetMapping("/stream-falha/{id}")
		SseEmitter streamFalha(@PathVariable UUID id) {
			return this.emissores.inscrever(id, () -> {
				throw new IllegalStateException("job inexistente");
			});
		}

	}

	@Test
	void aFotografiaSaiPrimeiroComIdENome() throws Exception {
		UUID jobId = UUID.randomUUID();

		MvcResult resultado = this.mockMvc.perform(get("/stream/{id}", jobId))
			.andExpect(request().asyncStarted())
			.andReturn();

		String corpo = resultado.getResponse().getContentAsString();
		assertThat(corpo).contains("event:estado").contains("id:1").contains("fotografia");
		assertThat(this.emissores.conexoesAtivas()).isEqualTo(1);
	}

	@Test
	void emitirChegaComIdMaiorQueOAFotografia() throws Exception {
		UUID jobId = UUID.randomUUID();
		MvcResult resultado = this.mockMvc.perform(get("/stream/{id}", jobId))
			.andExpect(request().asyncStarted())
			.andReturn();

		this.emissores.emitir(jobId, EventoSse.de("etapa", "progresso"));

		String corpo = resultado.getResponse().getContentAsString();
		assertThat(corpo).contains("event:etapa").contains("id:2").contains("progresso");
	}

	@Test
	void jobSemClienteConectadoEDescartadoSemErro() {
		assertThatCode(() -> this.emissores.emitir(UUID.randomUUID(), EventoSse.de("etapa", "x")))
			.doesNotThrowAnyException();
	}

	@Test
	void umSupplierQueLancaNaoDeixaEmissorRegistrado() {
		UUID jobId = UUID.randomUUID();

		try {
			this.mockMvc.perform(get("/stream-falha/{id}", jobId));
		}
		catch (Throwable esperado) {
			// A exceção do Supplier propaga pelo caminho síncrono normal de tratamento de
			// erro do MockMvc; o que importa aqui é que nenhum emissor ficou registrado.
		}

		assertThat(this.emissores.conexoesAtivas()).isZero();
	}

	@Test
	void completarRemoveOEmissor() throws Exception {
		UUID jobId = UUID.randomUUID();
		MvcResult resultado = this.mockMvc.perform(get("/stream/{id}", jobId))
			.andExpect(request().asyncStarted())
			.andReturn();
		assertThat(this.emissores.conexoesAtivas()).isEqualTo(1);

		asyncContextDe(resultado).complete();

		assertThat(this.emissores.conexoesAtivas()).isZero();
	}

	@Test
	void erroDoClienteRemoveOEmissor() throws Exception {
		UUID jobId = UUID.randomUUID();
		MvcResult resultado = this.mockMvc.perform(get("/stream/{id}", jobId))
			.andExpect(request().asyncStarted())
			.andReturn();

		MockAsyncContext asyncContext = asyncContextDe(resultado);
		for (AsyncListener listener : List.copyOf(asyncContext.getListeners())) {
			listener.onError(new AsyncEvent(asyncContext, new IOException("conexão perdida")));
		}

		assertThat(this.emissores.conexoesAtivas()).isZero();
	}

	@Test
	void timeoutRemoveOEmissor() throws Exception {
		UUID jobId = UUID.randomUUID();
		MvcResult resultado = this.mockMvc.perform(get("/stream/{id}", jobId))
			.andExpect(request().asyncStarted())
			.andReturn();

		MockAsyncContext asyncContext = asyncContextDe(resultado);
		for (AsyncListener listener : List.copyOf(asyncContext.getListeners())) {
			listener.onTimeout(new AsyncEvent(asyncContext));
		}

		assertThat(this.emissores.conexoesAtivas()).isZero();
	}

	@Test
	void fotografiaTerminalNaoDeixaEmissorRegistrado() throws Exception {
		UUID jobId = UUID.randomUUID();

		this.mockMvc.perform(get("/stream-terminal/{id}", jobId)).andReturn();

		assertThat(this.emissores.conexoesAtivas()).isZero();
	}

	private static MockAsyncContext asyncContextDe(MvcResult resultado) {
		return (MockAsyncContext) Objects.requireNonNull(resultado.getRequest().getAsyncContext());
	}

	@Test
	void enviarHeartbeatNaoLancaSemEmissores() {
		assertThatCode(() -> this.emissores.enviarHeartbeat()).doesNotThrowAnyException();
	}

	@Test
	void stopFechaTodoEmissorEZeraOMapa() throws Exception {
		UUID jobId = UUID.randomUUID();
		this.mockMvc.perform(get("/stream/{id}", jobId)).andExpect(request().asyncStarted()).andReturn();
		assertThat(this.emissores.conexoesAtivas()).isEqualTo(1);

		this.emissores.stop();

		assertThat(this.emissores.conexoesAtivas()).isZero();
	}

}
