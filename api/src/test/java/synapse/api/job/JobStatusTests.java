package synapse.api.job;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.EnumSet;
import java.util.Set;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

import static org.assertj.core.api.Assertions.assertThat;

class JobStatusTests {

	// --- Caminhos válidos -----------------------------------------------------------

	@Test
	void permiteOCaminhoFelizCompleto() {
		assertThat(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS.permiteTransicaoPara(JobStatus.GERANDO_REGRA)).isTrue();
		assertThat(JobStatus.GERANDO_REGRA.permiteTransicaoPara(JobStatus.SIMULANDO)).isTrue();
		assertThat(JobStatus.SIMULANDO.permiteTransicaoPara(JobStatus.AGUARDANDO_DECISAO_USUARIO)).isTrue();
		assertThat(JobStatus.AGUARDANDO_DECISAO_USUARIO.permiteTransicaoPara(JobStatus.LIBERADO)).isTrue();
	}

	@Test
	void permiteOLoopDeAdaptacaoAPartirDaSimulacaoInviavel() {
		assertThat(JobStatus.SIMULANDO.permiteTransicaoPara(JobStatus.SIMULACAO_INVIAVEL)).isTrue();
		assertThat(JobStatus.SIMULACAO_INVIAVEL.permiteTransicaoPara(JobStatus.GERANDO_REGRA)).isTrue();
		assertThat(JobStatus.SIMULACAO_INVIAVEL.permiteTransicaoPara(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS))
			.isTrue();
	}

	@Test
	void permiteCancelarOuArquivarNosPontosDeDecisao() {
		assertThat(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS.permiteTransicaoPara(JobStatus.CANCELADO)).isTrue();
		assertThat(JobStatus.SIMULACAO_INVIAVEL.permiteTransicaoPara(JobStatus.CANCELADO)).isTrue();
		assertThat(JobStatus.SIMULACAO_INVIAVEL.permiteTransicaoPara(JobStatus.ARQUIVADO)).isTrue();
		assertThat(JobStatus.AGUARDANDO_DECISAO_USUARIO.permiteTransicaoPara(JobStatus.CANCELADO)).isTrue();
		assertThat(JobStatus.AGUARDANDO_DECISAO_USUARIO.permiteTransicaoPara(JobStatus.ARQUIVADO)).isTrue();
	}

	@Test
	void permiteErrarAPartirDeGerandoRegraOuSimulando() {
		assertThat(JobStatus.GERANDO_REGRA.permiteTransicaoPara(JobStatus.ERRO)).isTrue();
		assertThat(JobStatus.SIMULANDO.permiteTransicaoPara(JobStatus.ERRO)).isTrue();
	}

	// --- Caminhos inválidos -----------------------------------------------------------

	@Test
	void recusaLiberarDiretoDaSimulacaoInviavel() {
		assertThat(JobStatus.SIMULACAO_INVIAVEL.permiteTransicaoPara(JobStatus.LIBERADO)).isFalse();
	}

	@Test
	void recusaPularEtapasDaConfirmacaoDiretoParaSimulando() {
		assertThat(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS.permiteTransicaoPara(JobStatus.SIMULANDO)).isFalse();
	}

	@Test
	void recusaVoltarDeGerandoRegraParaAguardandoConfirmacao() {
		assertThat(JobStatus.GERANDO_REGRA.permiteTransicaoPara(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS)).isFalse();
	}

	@ParameterizedTest
	@EnumSource(value = JobStatus.class, names = { "LIBERADO", "CANCELADO", "ARQUIVADO", "ERRO" })
	void recusaQualquerTransicaoAPartirDeUmEstadoTerminal(JobStatus terminal) {
		assertThat(terminal.terminal()).isTrue();
		for (JobStatus destino : JobStatus.values()) {
			assertThat(terminal.permiteTransicaoPara(destino)).as("%s -> %s", terminal, destino).isFalse();
		}
	}

	/**
	 * O bloqueio de {@code liberado} a partir de {@code simulacao_inviavel} é da máquina
	 * de estados: não existe aresta direta entre os dois, e o único predecessor de
	 * {@code liberado} no grafo é {@code aguardando_decisao_usuario} - alcançável apenas
	 * por uma simulação concluída ({@code simulando}). Uma nova tentativa após adaptação
	 * da regra tem que passar de novo por uma simulação; não há atalho.
	 */
	@Test
	void oUnicoPredecessorDeLiberadoEAguardandoDecisaoUsuario() {
		Set<JobStatus> predecessores = EnumSet.noneOf(JobStatus.class);
		for (JobStatus origem : JobStatus.values()) {
			if (origem.permiteTransicaoPara(JobStatus.LIBERADO)) {
				predecessores.add(origem);
			}
		}
		assertThat(predecessores).containsExactly(JobStatus.AGUARDANDO_DECISAO_USUARIO);
	}

	@Test
	void oCaminhoFelizAlcancaLiberadoAPartirDaAguardandoConfirmacao() {
		assertThat(alcancaveis(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS)).contains(JobStatus.LIBERADO);
	}

	private static Set<JobStatus> alcancaveis(JobStatus origem) {
		Set<JobStatus> visitados = EnumSet.noneOf(JobStatus.class);
		Deque<JobStatus> fronteira = new ArrayDeque<>();
		fronteira.add(origem);
		while (!fronteira.isEmpty()) {
			JobStatus atual = fronteira.remove();
			for (JobStatus destino : JobStatus.values()) {
				if (atual.permiteTransicaoPara(destino) && visitados.add(destino)) {
					fronteira.add(destino);
				}
			}
		}
		return visitados;
	}

}
