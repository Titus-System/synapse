package synapse.api.job;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Objects;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ExemplosDeContratoTests {

	private static final Path DIRETORIO_EXEMPLOS = localizarDiretorioExemplos();

	private final ObjectMapper objectMapper = new ObjectMapper();

	@Test
	void desserializaOConteudoDaSubmissao() throws IOException {
		ConteudoSubmissaoDto conteudo = desserializar("domain/submissao-conteudo.json", ConteudoSubmissaoDto.class);
		VigenciaDto vigencia = Objects.requireNonNull(conteudo.nucleo().vigencia());

		assertThat(vigencia.inicio()).isEqualTo("2025-11");
		assertThat(conteudo.nucleo().percentual()).isEqualByComparingTo("0.03");
		assertThat(conteudo.texto_livre()).contains("MATRIC-422");
	}

	@Test
	void desserializaARepresentacaoDaRegra() throws IOException {
		RepresentacaoRegraDto regra = desserializar("domain/representacao-regra.json", RepresentacaoRegraDto.class);

		assertThat(regra.nucleo().percentual()).isEqualByComparingTo("0.025");
		assertThat(regra.especificacoes()).isEmpty();
	}

	@Test
	void desserializaOResultadoDaSimulacao() throws IOException {
		ResultadoSimulacaoDto resultado = desserializar("domain/resultado-simulacao.json", ResultadoSimulacaoDto.class);
		TotaisSimulacaoDto totais = Objects.requireNonNull(resultado.totais());
		DecomposicaoResultadoDto decomposicao = Objects.requireNonNull(resultado.decomposicao());

		assertThat(totais.orcamento()).isEqualTo(new BigDecimal("485000.0"));
		assertThat(resultado.assercoes()).hasSize(3);
		assertThat(decomposicao.competencia()).containsEntry("2025-08", BigDecimal.ZERO);
	}

	@Test
	void desserializaOEventoDeEtapaAlterada() throws IOException {
		EtapaAlteradaDto evento = desserializar("events/etapa-alterada.json", EtapaAlteradaDto.class);

		assertThat(evento.job_id()).isEqualTo(UUID.fromString("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021"));
		assertThat(evento.etapa()).isEqualTo("geracao_codigo");
		assertThat(evento.status()).isEqualTo("iniciada");
	}

	@Test
	void desserializaOEventoDeRegraSubmetida() throws IOException {
		RegraSubmetidaDto evento = desserializar("events/regra-submetida.json", RegraSubmetidaDto.class);

		assertThat(evento.job_id()).isEqualTo(UUID.fromString("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021"));
		assertThat(evento.origem()).isEqualTo("formulario");
		assertThat(evento.competencias()).containsExactly("2025-08", "2025-11");
		assertThat(evento.orcamento()).isEqualByComparingTo("485000.0");
		assertThat(evento.submissao_id()).isEqualTo(UUID.fromString("b81e0f4c-52a9-4f0b-8a3d-7c2e5d10ab93"));
		assertThat(evento.regra_id()).isEqualTo(UUID.fromString("9c7d3e21-4a6b-4c8d-9e0f-1a2b3c4d5e6f"));

		ContratoDeEvento.validar("regra-submetida", Files.readString(exemplo("events/regra-submetida.json")));
	}

	/**
	 * A origem {@code voz} não tem {@code regra_id} - o schema só o exige nas origens
	 * {@code formulario} e {@code reprocessamento}.
	 * {@code FAIL_ON_MISSING_CREATOR_PROPERTIES} dispara para qualquer componente
	 * ausente, {@code @Nullable} ou não (verificado no bytecode de
	 * {@code PropertyValueBuffer}), então este cenário lê sem essa feature - é o que
	 * prova que o DTO tolera o ramo condicional do schema.
	 */
	@Test
	void desserializaOEventoDeRegraSubmetidaDeOrigemVoz() throws IOException {
		RegraSubmetidaDto evento = this.objectMapper.readerFor(RegraSubmetidaDto.class)
			.with(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
			.readValue(Files.readString(exemplo("events/regra-submetida-voz.json")));

		assertThat(evento.origem()).isEqualTo("voz");
		assertThat(evento.submissao_id()).isEqualTo(UUID.fromString("d7e8f9a0-1b2c-4d3e-8f40-5a6b7c8d9e0f"));
		assertThat(evento.regra_id()).isNull();
		assertThat(evento.orcamento()).isNull();

		ContratoDeEvento.validar("regra-submetida", Files.readString(exemplo("events/regra-submetida-voz.json")));
	}

	@ParameterizedTest
	@ValueSource(strings = { "0", "485000.1234567890123456789" })
	void schemaAceitaOrcamentoNaoNegativo(String valor) throws IOException {
		ObjectNode payload = (ObjectNode) this.objectMapper
			.readTree(Files.readString(exemplo("events/regra-submetida.json")));
		payload.put("orcamento", new BigDecimal(valor));

		ContratoDeEvento.validar("regra-submetida", payload.toString());
	}

	@ParameterizedTest
	@ValueSource(strings = { "-0.01", "\"485000\"", "null", "true" })
	void schemaRecusaOrcamentoInvalido(String valor) throws IOException {
		ObjectNode payload = (ObjectNode) this.objectMapper
			.readTree(Files.readString(exemplo("events/regra-submetida.json")));
		payload.set("orcamento", this.objectMapper.readTree(valor));

		assertThatThrownBy(() -> ContratoDeEvento.validar("regra-submetida", payload.toString()))
			.isInstanceOf(AssertionError.class)
			.hasMessageContaining("orcamento");
	}

	/**
	 * O schema recusa {@code null} explícito, então o campo ausente tem de continuar
	 * ausente na ida e na volta - é o que {@code @JsonInclude(NON_NULL)} garante.
	 */
	@Test
	void orcamentoAusentePermaneceAusenteAoSerializar() throws IOException {
		ObjectNode payload = (ObjectNode) this.objectMapper
			.readTree(Files.readString(exemplo("events/regra-submetida.json")));
		payload.remove("orcamento");
		RegraSubmetidaDto evento = this.objectMapper.readValue(payload.toString(), RegraSubmetidaDto.class);

		String serializado = this.objectMapper.writeValueAsString(evento);

		assertThat(this.objectMapper.readTree(serializado).has("orcamento")).isFalse();
		ContratoDeEvento.validar("regra-submetida", serializado);
	}

	@Test
	void desserializaOEventoDeSimulacaoConcluida() throws IOException {
		SimulacaoConcluidaDto evento = desserializar("events/simulacao-concluida.json", SimulacaoConcluidaDto.class);

		assertThat(evento.job_id()).isEqualTo(UUID.fromString("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021"));
		assertThat(evento.resultado_id()).isEqualTo(UUID.fromString("b81e0f4c-52a9-4f0b-8a3d-7c2e5d10ab93"));
		assertThat(evento.status()).isEqualTo("sucesso");
		assertThat(evento.veredito()).isEqualTo("inviavel");

		ContratoDeEvento.validar("simulacao-concluida", Files.readString(exemplo("events/simulacao-concluida.json")));
	}

	private <T> T desserializar(String caminhoRelativo, Class<T> tipo) throws IOException {
		return this.objectMapper.readerFor(tipo)
			.with(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES,
					DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
			.readValue(Files.readString(exemplo(caminhoRelativo)));
	}

	private static Path exemplo(String caminhoRelativo) {
		return DIRETORIO_EXEMPLOS.resolve(caminhoRelativo);
	}

	private static Path localizarDiretorioExemplos() {
		Path diretorioAtual = Path.of("").toAbsolutePath();
		while (diretorioAtual != null) {
			Path diretorioExemplos = diretorioAtual.resolve("contracts/examples");
			if (Files.isDirectory(diretorioExemplos)) {
				return diretorioExemplos;
			}
			diretorioAtual = diretorioAtual.getParent();
		}

		throw new IllegalStateException("Diretório contracts/examples não encontrado a partir do diretório atual.");
	}

}
