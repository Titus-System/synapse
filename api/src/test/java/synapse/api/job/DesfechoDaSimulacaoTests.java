package synapse.api.job;

import java.util.Objects;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.NullSource;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;

class DesfechoDaSimulacaoTests {

	// --- Casos válidos ----------------------------------------------------------------

	@Test
	void sucessoComVereditoViavelLevaAAguardandoDecisaoUsuarioSemMotivo() {
		DesfechoDaSimulacao desfecho = Objects.requireNonNull(DesfechoDaSimulacao.de("sucesso", "viavel"));

		assertThat(desfecho.destino()).isEqualTo(JobStatus.AGUARDANDO_DECISAO_USUARIO);
		assertThat(desfecho.motivoDaTrilha()).isNull();
		assertThat(desfecho.razaoLocalizada()).isNull();
	}

	/**
	 * O ticket só especifica {@code viavel}/{@code inviavel}; o schema admite também
	 * {@code indeterminado}. Há números confiáveis, só não se fechou o julgamento
	 * orçamentário - e só {@code inviavel} bloqueia a liberação (ARCHITECTURE.md §3.4).
	 */
	@Test
	void sucessoComVereditoIndeterminadoLevaAAguardandoDecisaoUsuario() {
		DesfechoDaSimulacao desfecho = Objects.requireNonNull(DesfechoDaSimulacao.de("sucesso", "indeterminado"));

		assertThat(desfecho.destino()).isEqualTo(JobStatus.AGUARDANDO_DECISAO_USUARIO);
		assertThat(desfecho.motivoDaTrilha()).isNull();
	}

	@Test
	void sucessoComVereditoInviavelLevaASimulacaoInviavelComMotivo() {
		DesfechoDaSimulacao desfecho = Objects.requireNonNull(DesfechoDaSimulacao.de("sucesso", "inviavel"));

		assertThat(desfecho.destino()).isEqualTo(JobStatus.SIMULACAO_INVIAVEL);
		assertThat(desfecho.motivoDaTrilha()).isEqualTo("inviavel");
		assertThat(desfecho.razaoLocalizada()).isNotBlank();
	}

	/**
	 * Critério nº 3: asserção invariante violada não é inviabilidade. O código rodou e
	 * produziu números, mas uma invariante foi violada e o número não vale - é erro, não
	 * um veredito sobre um número confiável.
	 */
	@Test
	void assercaoVioladaLevaAErroENaoASimulacaoInviavel() {
		DesfechoDaSimulacao desfecho = Objects.requireNonNull(DesfechoDaSimulacao.de("assercao_violada", null));

		assertThat(desfecho.destino()).isEqualTo(JobStatus.ERRO);
		assertThat(desfecho.destino()).isNotEqualTo(JobStatus.SIMULACAO_INVIAVEL);
		assertThat(desfecho.motivoDaTrilha()).isEqualTo("assercao_violada");
	}

	/** Critério nº 4: os dois ficam registrados de forma distinguível. */
	@Test
	void erroCodigoEErroInfraLevamAErroComMotivosDistintos() {
		DesfechoDaSimulacao erroCodigo = Objects.requireNonNull(DesfechoDaSimulacao.de("erro_codigo", null));
		DesfechoDaSimulacao erroInfra = Objects.requireNonNull(DesfechoDaSimulacao.de("erro_infra", null));

		assertThat(erroCodigo.destino()).isEqualTo(JobStatus.ERRO);
		assertThat(erroInfra.destino()).isEqualTo(JobStatus.ERRO);
		assertThat(erroCodigo.motivoDaTrilha()).isEqualTo("erro_codigo");
		assertThat(erroInfra.motivoDaTrilha()).isEqualTo("erro_infra");
		assertThat(erroCodigo.motivoDaTrilha()).isNotEqualTo(erroInfra.motivoDaTrilha());
	}

	/**
	 * O veredito só é lido em {@code sucesso}: o schema o declara ausente nos demais
	 * status, e um veredito presente por engano não deve mudar o destino.
	 */
	@ParameterizedTest
	@CsvSource({ "assercao_violada, viavel", "erro_codigo, inviavel", "erro_infra, indeterminado" })
	void statusDeErroIgnoraUmVereditoPresenteIndevidamente(String status, String veredito) {
		DesfechoDaSimulacao desfecho = Objects.requireNonNull(DesfechoDaSimulacao.de(status, veredito));

		assertThat(desfecho.destino()).isEqualTo(JobStatus.ERRO);
	}

	// --- Casos recusados
	// ----------------------------------------------------------------

	@Test
	void sucessoSemVereditoReconhecivelNaoResolve() {
		assertThat(DesfechoDaSimulacao.de("sucesso", null)).isNull();
	}

	@Test
	void sucessoComVereditoForaDoVocabularioNaoResolve() {
		assertThat(DesfechoDaSimulacao.de("sucesso", "quase_viavel")).isNull();
	}

	@ParameterizedTest
	@ValueSource(strings = { "erro", "concluido", "" })
	void statusForaDoVocabularioNaoResolve(String status) {
		assertThat(DesfechoDaSimulacao.de(status, null)).isNull();
	}

	@ParameterizedTest
	@NullSource
	void statusNuloNaoResolve(String status) {
		assertThat(DesfechoDaSimulacao.de(status, "viavel")).isNull();
	}

}
