package synapse.api.job;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;

class MotivoDaParadaTests {

	@ParameterizedTest
	@EnumSource(value = DesfechoDaSimulacao.class,
			names = { "INVIAVEL", "ASSERCAO_VIOLADA", "ERRO_CODIGO", "ERRO_INFRA" })
	void aRazaoDaConsultaEAMesmaQueOSseEmiteParaCadaDesfecho(DesfechoDaSimulacao desfecho) {
		assertThat(MotivoDaParada.razaoLocalizada(desfecho.destino(), desfecho.motivoDaTrilha()))
			.isEqualTo(desfecho.razaoLocalizada())
			.isNotBlank();
	}

	@Test
	void osTresErrosDeExecucaoTemRazoesDistintas() {
		assertThat(MotivoDaParada.razaoLocalizada(JobStatus.ERRO, "erro_codigo"))
			.isNotEqualTo(MotivoDaParada.razaoLocalizada(JobStatus.ERRO, "erro_infra"))
			.isNotEqualTo(MotivoDaParada.razaoLocalizada(JobStatus.ERRO, "assercao_violada"));
	}

	@ParameterizedTest
	@EnumSource(EtapaDoGrafo.class)
	void falhaAnteriorASimulacaoTemAMesmaRazaoEmQualquerEtapa(EtapaDoGrafo etapa) {
		assertThat(MotivoDaParada.razaoLocalizada(JobStatus.ERRO, MotivoDaParada.falhaNaEtapa(etapa)))
			.isEqualTo(MotivoDaParada.FALHA_ANTES_DA_SIMULACAO);
	}

	@Test
	void ausenciaDeTokenNaoDaMotivo() {
		for (JobStatus status : JobStatus.values()) {
			assertThat(MotivoDaParada.razaoLocalizada(status, null)).isNull();
		}
	}

	@ParameterizedTest
	@ValueSource(strings = { "simulacao_concluida_antecipada", "sugestao_adaptacao_proposta", "erro_etapa_inexistente",
			"erro_", "qualquer_coisa", "" })
	void tokenSemParadaOuDesconhecidoNaoDaMotivoEmNenhumEstado(String token) {
		for (JobStatus status : JobStatus.values()) {
			assertThat(MotivoDaParada.razaoLocalizada(status, token)).as("%s em %s", token, status).isNull();
		}
	}

	@Test
	void causaDeOutroEstadoNaoEHerdadaPeloEstadoCorrente() {
		assertThat(MotivoDaParada.razaoLocalizada(JobStatus.GERANDO_REGRA, "inviavel")).isNull();
		assertThat(MotivoDaParada.razaoLocalizada(JobStatus.AGUARDANDO_DECISAO_USUARIO, "inviavel")).isNull();
		assertThat(MotivoDaParada.razaoLocalizada(JobStatus.SIMULACAO_INVIAVEL, "erro_codigo")).isNull();
		assertThat(MotivoDaParada.razaoLocalizada(JobStatus.SIMULANDO, "erro_geracao_codigo")).isNull();
		assertThat(MotivoDaParada.razaoLocalizada(JobStatus.SIMULACAO_INVIAVEL,
				MotivoDaParada.falhaNaEtapa(EtapaDoGrafo.GERACAO_CODIGO)))
			.isNull();
	}

}
