package synapse.api.job;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.function.Function;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.mockito.ArgumentCaptor;
import tools.jackson.databind.json.JsonMapper;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.security.PapelDoUsuario;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.job.JobsDeSubmissoes.CorrecaoRecusada;
import synapse.api.job.JobsDeSubmissoes.Rodada;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class ReceberCorrecaoTests {

	private static final UUID JOB = UUID.randomUUID();

	private static final UUID USUARIO = UUID.randomUUID();

	private static final UUID REGRA = UUID.randomUUID();

	private static final UUID RODADA = UUID.randomUUID();

	private static final UUID SUBMISSAO = UUID.randomUUID();

	private static final Instant AGORA = Instant.parse("2026-10-13T20:00:00Z");

	private static final AcessoDoUsuario RH = new AcessoDoUsuario(USUARIO, PapelDoUsuario.PROFISSIONAL_RH);

	private final JobRepository jobs = mock(JobRepository.class);

	private final RodadasRepository rodadas = mock(RodadasRepository.class);

	private final Outbox outbox = mock(Outbox.class);

	private final Function<UUID, UUID> gravar = mock();

	private final JobsDeSubmissoesService service = new JobsDeSubmissoesService(jobs, mock(MaquinaDeEstadosDoJob.class),
			new AutorizadorDeJob(jobs), outbox, new CorrelationContext(), mock(AppMetrics.class),
			mock(EmissoresSse.class), rodadas);

	@BeforeEach
	void preparar() {
		when(jobs.buscarProprietario(JOB)).thenReturn(List.of(USUARIO));
		when(jobs.buscarContextoComTrava(JOB))
			.thenReturn(List.of(contexto(JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS)));
		when(rodadas.abertas(JOB)).thenReturn(List.of(rodada(EstadoRodada.PENDENTE)));
		when(rodadas.buscar(RODADA)).thenReturn(rodada(EstadoRodada.EM_REEXTRACAO));
		when(gravar.apply(RODADA)).thenReturn(SUBMISSAO);
	}

	private static JobRepository.ContextoDoJob contexto(JobStatus status) {
		return new JobRepository.ContextoDoJob(JOB, status, "texto", List.of("2025-11"),
				new BigDecimal("-12.1234567890123456789"), new BigDecimal("12345.67890123456789"), null);
	}

	private static Rodada rodada(EstadoRodada estado) {
		return new Rodada(RODADA, null, REGRA,
				new JsonMapper().readTree("[{\"elementos\":[\"nucleo.percentual\"],\"motivo\":\"ausente\"}]"), null,
				null, estado.paraColuna(), AGORA);
	}

	@Test
	void autorizaTravaConfereAntesDeGravarERegistraOContratoDoEvento() throws Exception {
		var recebida = service.corrigir(JOB, RH, gravar, AGORA);
		var ordem = inOrder(jobs, rodadas, gravar, outbox);
		ordem.verify(jobs).buscarProprietario(JOB);
		ordem.verify(jobs).buscarContextoComTrava(JOB);
		ordem.verify(rodadas).abertas(JOB);
		ordem.verify(gravar).apply(RODADA);
		ordem.verify(rodadas).receber(RODADA, SUBMISSAO, AGORA);
		var evento = ArgumentCaptor.forClass(CorrecaoSubmetidaDto.class);
		ordem.verify(outbox).registrar(eq(JOB), eq(EventoOutbox.CORRECAO_SUBMETIDA), evento.capture());
		assertThat(recebida.submissaoId()).isEqualTo(SUBMISSAO);
		assertThat(recebida.rodada().estado()).isEqualTo("em_reextracao");
		assertThat(evento.getValue())
			.isEqualTo(new CorrecaoSubmetidaDto(JOB, REGRA, SUBMISSAO, contexto(JobStatus.GERANDO_REGRA).competencias(),
					contexto(JobStatus.GERANDO_REGRA).orcamento(), contexto(JobStatus.GERANDO_REGRA).metaVenda()));
		ContratoDeEvento.validar("correcao-submetida", new JsonMapper().writeValueAsString(evento.getValue()));
	}

	@Test
	void omiteParametrosAusentesConformeSchema() throws Exception {
		when(jobs.buscarContextoComTrava(JOB)).thenReturn(List.of(new JobRepository.ContextoDoJob(JOB,
				JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS, "texto", List.of("2025-11"), null, null, null)));
		service.corrigir(JOB, RH, gravar, AGORA);
		var evento = ArgumentCaptor.forClass(CorrecaoSubmetidaDto.class);
		verify(outbox).registrar(eq(JOB), eq(EventoOutbox.CORRECAO_SUBMETIDA), evento.capture());
		String payload = new JsonMapper().writeValueAsString(evento.getValue());
		ContratoDeEvento.validar("correcao-submetida", payload);
		assertThat(payload).doesNotContain("orcamento", "meta_venda", "texto", "transcricao");
	}

	@ParameterizedTest
	@EnumSource(value = JobStatus.class, names = "AGUARDANDO_CONFIRMACAO_PARAMETROS", mode = EnumSource.Mode.EXCLUDE)
	void recusaTodosOsOutrosEstadosSemChamarAGravacao(JobStatus estado) {
		when(jobs.buscarContextoComTrava(JOB)).thenReturn(List.of(contexto(estado)));
		recusa(RH, 409, "estado_invalido");
	}

	@ParameterizedTest
	@EnumSource(value = EstadoRodada.class, names = "PENDENTE", mode = EnumSource.Mode.EXCLUDE)
	void soAceitaRodadaPendente(EstadoRodada estado) {
		when(rodadas.abertas(JOB)).thenReturn(List.of(rodada(estado)));
		recusa(RH, 409, "estado_invalido");
	}

	@Test
	void recusaSemRodada() {
		when(rodadas.abertas(JOB)).thenReturn(List.of());
		recusa(RH, 409, "estado_invalido");
	}

	@Test
	void auditorDonoNaoPodeCorrigir() {
		recusa(new AcessoDoUsuario(USUARIO, PapelDoUsuario.AUDITOR), 403, "sem_permissao");
		verify(jobs, never()).buscarContextoComTrava(any());
	}

	@Test
	void outroDonoNaoPodeCorrigir() {
		recusa(new AcessoDoUsuario(UUID.randomUUID(), PapelDoUsuario.PROFISSIONAL_RH), 403, "sem_permissao");
		verify(jobs, never()).buscarContextoComTrava(any());
	}

	@Test
	void inexistenteNaoGrava() {
		when(jobs.buscarProprietario(JOB)).thenReturn(List.of());
		recusa(RH, 404, "job_nao_encontrado");
	}

	private void recusa(AcessoDoUsuario acesso, int status, String codigo) {
		assertThatThrownBy(() -> service.corrigir(JOB, acesso, gravar, AGORA))
			.isInstanceOfSatisfying(CorrecaoRecusada.class, ex -> {
				assertThat(ex.status()).isEqualTo(status);
				assertThat(ex.codigo()).isEqualTo(codigo);
			});
		verifyNoInteractions(gravar, outbox);
		verify(rodadas, never()).receber(any(), any(), any());
	}

}
