package synapse.api.job;

import java.io.IOException;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Objects;
import java.util.UUID;

import org.junit.jupiter.api.Test;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;

import static org.assertj.core.api.Assertions.assertThat;

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

		assertThat(resultado.totais().orcamento()).isEqualTo(new BigDecimal("485000.0"));
		assertThat(resultado.assercoes()).hasSize(3);
		assertThat(resultado.decomposicao().competencia()).containsEntry("2025-08", BigDecimal.ZERO);
	}

	@Test
	void desserializaOEventoDeEtapaAlterada() throws IOException {
		EtapaAlteradaDto evento = desserializar("events/etapa-alterada.json", EtapaAlteradaDto.class);

		assertThat(evento.job_id()).isEqualTo(UUID.fromString("3f2b1c40-0d18-4a51-9f2e-6c1d9a77b021"));
		assertThat(evento.etapa()).isEqualTo("geracao_codigo");
		assertThat(evento.status()).isEqualTo("iniciada");
	}

	private <T> T desserializar(String caminhoRelativo, Class<T> tipo) throws IOException {
		Path caminhoDoExemplo = DIRETORIO_EXEMPLOS.resolve(caminhoRelativo);
		return this.objectMapper.readerFor(tipo)
			.with(DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES,
					DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
			.readValue(Files.readString(caminhoDoExemplo));
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
