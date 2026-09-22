package synapse.api.job;

import java.time.Instant;
import java.util.UUID;
import java.util.stream.Stream;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class CriarJobControllerTests {

	static final UUID USUARIO = UUID.fromString("22222222-2222-4222-8222-222222222222");

	static final String FORMULARIO = """
			{"origem":"formulario","competencias":["2025-11"],"orcamento":485000.1234567890123456789,
			 "conteudo":{"nucleo":{"vigencia":{"inicio":"2025-11","fim":"2025-11"},
			 "loja":["13"],"marca":["10","20"],"cargo":["100","300"],"percentual":0.025},"texto_livre":null}}
			""";

	private final CriarJobService service = mock(CriarJobService.class);

	private MockMvc mvc;

	@BeforeEach
	void preparar() {
		this.mvc = MockMvcBuilders.standaloneSetup(new CriarJobController(this.service))
			.setControllerAdvice(new CriarJobAdvice())
			.build();
	}

	@Test
	void semPrincipalResponde201ComLocationEExatamenteOsCamposIniciais() throws Exception {
		UUID jobId = UUID.randomUUID();
		when(this.service.criar(any())).thenAnswer(invocacao -> {
			CriarJobRequisicao requisicao = invocacao.getArgument(0);
			return new JobCriadoDto(jobId, "gerando_regra", "formulario", requisicao.competencias(),
					requisicao.orcamento(), Instant.parse("2026-09-16T15:00:00Z"), UUID.randomUUID(),
					new RegraCriadaDto(UUID.randomUUID(), 1, "confirmacao_usuario", requisicao.representacao(),
							Instant.parse("2026-09-16T15:00:00Z")));
		});

		String resposta = this.mvc.perform(post("/jobs").contentType(MediaType.APPLICATION_JSON).content(FORMULARIO))
			.andExpect(status().isCreated())
			.andExpect(header().string("Location", "/api/jobs/" + jobId))
			.andExpect(jsonPath("$.status").value("gerando_regra"))
			.andExpect(jsonPath("$.regra.versao").value(1))
			.andExpect(jsonPath("$.regra.origem").value("confirmacao_usuario"))
			.andExpect(jsonPath("$.regra.representacao.especificacoes").isEmpty())
			.andReturn()
			.getResponse()
			.getContentAsString();
		var job = new JsonMapper().readTree(resposta);
		assertThat(job.propertyNames()).containsExactlyInAnyOrder("id", "status", "origem", "competencias", "orcamento",
				"criado_em", "submissao_id", "regra");
		assertThat(job.path("regra").propertyNames()).containsExactlyInAnyOrder("id", "versao", "origem",
				"representacao", "criada_em");
		verify(this.service).criar(any());
	}

	@ParameterizedTest
	@MethodSource("requisicoesInvalidas")
	void recusaRequisicaoInvalidaAntesDePersistir(String corpo) throws Exception {
		this.mvc.perform(post("/jobs").contentType(MediaType.APPLICATION_JSON).content(corpo))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"))
			.andExpect(jsonPath("$.mensagem").isNotEmpty());
		verifyNoInteractions(this.service);
	}

	static Stream<String> requisicoesInvalidas() {
		return Stream.of("", "{", "null", "[]", FORMULARIO + " {}", FORMULARIO.replace("formulario", "voz"),
				FORMULARIO.replace("formulario", "reprocessamento"), FORMULARIO.replace("formulario", "outra"),
				FORMULARIO.replace("\"origem\":\"formulario\",", ""),
				FORMULARIO.replace("485000.1234567890123456789", "null"),
				FORMULARIO.replace("485000.1234567890123456789", "\"485000\""),
				FORMULARIO.replace("\"orcamento\":485000.1234567890123456789,", ""),
				FORMULARIO.replace("[\"2025-11\"]", "[]"), FORMULARIO.replace("[\"2025-11\"]", "null"),
				FORMULARIO.replace("[\"2025-11\"]", "[\"2026-01\"]"),
				FORMULARIO.replace("[\"2025-11\"]", "[\"2025-06\"]"),
				FORMULARIO.replace("[\"2025-11\"]", "[\"2025-11\",\"2025-11\"]"),
				FORMULARIO.replace("[\"2025-11\"]", "[202511]"), FORMULARIO.replace("[\"2025-11\"]", "[null]"),
				FORMULARIO.replace("\"texto_livre\":null", "\"texto_livre\":5"),
				FORMULARIO.replace(",\"texto_livre\":null", ""));
	}

	@ParameterizedTest
	@ValueSource(strings = { "\"invalido\"", "[]" })
	void nucleoQueNaoEObjetoResponde400(String valor) throws Exception {
		JsonMapper json = new JsonMapper();
		ObjectNode corpo = (ObjectNode) json.readTree(FORMULARIO);
		((ObjectNode) corpo.path("conteudo")).set("nucleo", json.readTree(valor));
		this.mvc.perform(post("/jobs").contentType(MediaType.APPLICATION_JSON).content(corpo.toString()))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"))
			.andExpect(jsonPath("$.mensagem").value("O campo conteudo.nucleo é obrigatório e precisa ser um objeto."));
		verifyNoInteractions(this.service);
	}

	@ParameterizedTest
	@MethodSource("camposAusentes")
	void nucleoIncompletoResponde422ComCampoLocalizado(String campo, boolean nulo) throws Exception {
		ObjectNode corpo = (ObjectNode) new JsonMapper().readTree(FORMULARIO);
		ObjectNode nucleo = (ObjectNode) corpo.path("conteudo").path("nucleo");
		if (nulo) {
			nucleo.putNull(campo);
		}
		else {
			nucleo.remove(campo);
		}
		this.mvc.perform(post("/jobs").contentType(MediaType.APPLICATION_JSON).content(corpo.toString()))
			.andExpect(status().isUnprocessableContent())
			.andExpect(jsonPath("$.codigo").value("nucleo_incompleto"))
			.andExpect(jsonPath("$.elementos[0].ref").value("nucleo." + campo));
		verifyNoInteractions(this.service);
	}

	static Stream<Arguments> camposAusentes() {
		return Stream.of("vigencia", "loja", "marca", "cargo", "percentual")
			.flatMap(campo -> Stream.of(Arguments.of(campo, false), Arguments.of(campo, true)));
	}

	@ParameterizedTest
	@MethodSource("camposInvalidos")
	void campoInvalidoResponde400ComReferencia(String campo, String valor) throws Exception {
		JsonMapper json = new JsonMapper();
		ObjectNode corpo = (ObjectNode) json.readTree(FORMULARIO);
		((ObjectNode) corpo.path("conteudo").path("nucleo")).set(campo, json.readTree(valor));
		this.mvc.perform(post("/jobs").contentType(MediaType.APPLICATION_JSON).content(corpo.toString()))
			.andExpect(status().isBadRequest())
			.andExpect(jsonPath("$.codigo").value("requisicao_invalida"))
			.andExpect(jsonPath("$.elementos[0].ref").value("nucleo." + campo));
		verifyNoInteractions(this.service);
	}

	static Stream<Arguments> camposInvalidos() {
		return Stream.of(Arguments.of("vigencia", "{}"), Arguments.of("vigencia", "\"2025-11\""),
				Arguments.of("vigencia", "{\"inicio\":\"2025-13\",\"fim\":\"2025-11\"}"),
				Arguments.of("vigencia", "{\"inicio\":\"2025-12\",\"fim\":\"2025-11\"}"),
				Arguments.of("loja", "\"13\""), Arguments.of("loja", "[13]"), Arguments.of("marca", "[\"\"]"),
				Arguments.of("cargo", "[null]"), Arguments.of("percentual", "\"0.025\""));
	}

	@Test
	void semUsuarioAtivoResponde503ComErroDeDominio() throws Exception {
		when(this.service.criar(any())).thenThrow(CriarJobException.semUsuarioAtivo());
		this.mvc.perform(post("/jobs").contentType(MediaType.APPLICATION_JSON).content(FORMULARIO))
			.andExpect(status().isServiceUnavailable())
			.andExpect(jsonPath("$.codigo").value("usuario_ativo_indisponivel"))
			.andExpect(jsonPath("$.mensagem").value("Nenhum usuário ativo disponível para criar o job."));
	}

	@Test
	void naoExpoeErroDoJdbc() throws Exception {
		when(this.service.criar(any())).thenThrow(new DataIntegrityViolationException("regras SQL stack trace"));
		this.mvc.perform(post("/jobs").contentType(MediaType.APPLICATION_JSON).content(FORMULARIO))
			.andExpect(status().isInternalServerError())
			.andExpect(content().string(""));
	}

}
