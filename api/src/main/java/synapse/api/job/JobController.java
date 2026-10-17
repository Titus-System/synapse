package synapse.api.job;

import java.net.URI;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import org.jspecify.annotations.Nullable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;

import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import synapse.api.core.logging.CorrelationContext;
import synapse.api.core.metrics.AppMetrics;
import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.job.JobService.AcaoAplicada;

@RestController
class JobController {

	private static final Logger log = LoggerFactory.getLogger(JobController.class);

	private final JobService service;

	private final EmissoresSse emissores;

	private final CorrelationContext correlacao;

	private final AppMetrics metricas;

	JobController(JobService service, EmissoresSse emissores, CorrelationContext correlacao, AppMetrics metricas) {
		this.metricas = metricas;
		this.service = service;
		this.emissores = emissores;
		this.correlacao = correlacao;
	}

	@AutorizarJob(OperacaoJob.CRIAR)
	@PostMapping(path = "/jobs", consumes = "application/json", produces = "application/json")
	ResponseEntity<JobCriadoDto> criar(@RequestBody String corpo,
			@RequestAttribute(AutorizacaoJobsInterceptor.ACESSO) AcessoDoUsuario acesso) {
		JobCriadoDto job = this.service.criar(CriarJobRequisicao.deJson(corpo), acesso.usuarioId());
		return ResponseEntity.created(URI.create("/api/jobs/" + job.id())).body(job);
	}

	@AutorizarJob(OperacaoJob.LISTAR)
	@GetMapping(path = "/jobs", produces = "application/json")
	PaginaJobsDto listar(@RequestParam(name = "pagina", defaultValue = "0") int pagina,
			@RequestParam(name = "tamanho", defaultValue = "20") int tamanho,
			@RequestAttribute(AutorizacaoJobsInterceptor.ACESSO) AcessoDoUsuario acesso) {
		return this.service.listar(new ListarJobsRequisicao(pagina, tamanho), acesso);
	}

	@AutorizarJob(OperacaoJob.CONSULTAR)
	@GetMapping(path = "/jobs/{id}", produces = "application/json")
	JobDetalhadoDto buscar(@PathVariable UUID id) {
		return this.service.buscar(id);
	}

	@AutorizarJob(OperacaoJob.CONSULTAR)
	@GetMapping(path = "/jobs/{id}/simulacoes/{simulacaoId}/linhas", produces = "application/json")
	DetalhamentoSimulacaoDto detalharSimulacao(@PathVariable UUID id, @PathVariable UUID simulacaoId) {
		return this.service.detalharSimulacao(id, simulacaoId);
	}

	@AutorizarJob(OperacaoJob.ACOMPANHAR)
	@GetMapping(path = "/jobs/{id}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
	ResponseEntity<SseEmitter> acompanhar(@PathVariable("id") UUID id) {
		try (var escopo = this.correlacao.abrir(id.toString(), null)) {
			SseEmitter emissor = this.service.acompanhar(id);
			return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(emissor);
		}
	}

	@AutorizarJob(OperacaoJob.CONFIRMAR_PARAMETROS)
	@PostMapping(path = "/jobs/{id}/parameters", consumes = "application/json", produces = "application/json")
	ResponseEntity<JobCriadoDto> confirmar(@PathVariable("id") UUID id, @RequestBody String corpo) {
		long inicio = System.nanoTime();
		String resultado = "falha";
		try (var escopo = this.correlacao.abrir(id.toString(), null)) {
			this.metricas.jobRuns("confirmacao_parametros").increment();
			log.atInfo().log("confirmação de parâmetros iniciada");
			try {
				JobCriadoDto job = this.service.confirmar(id, ConfirmarParametrosRequisicao.deJson(corpo));
				resultado = "confirmada";
				return ResponseEntity.status(HttpStatus.ACCEPTED).body(job);
			}
			catch (RuntimeException ex) {
				if (ex instanceof ConfirmarParametrosException || ex instanceof TransicaoDeStatusInvalidaException
						|| ex instanceof JobNaoEncontradoException) {
					resultado = "recusada";
				}
				this.metricas.jobFailures("confirmacao_parametros").increment();
				throw ex;
			}
			finally {
				this.metricas.jobDuration("confirmacao_parametros")
					.record(System.nanoTime() - inicio, TimeUnit.NANOSECONDS);
				Level nivel = "confirmada".equals(resultado) ? Level.INFO
						: ("recusada".equals(resultado) ? Level.WARN : Level.ERROR);
				log.atLevel(nivel).addKeyValue("resultado", resultado).log("confirmação de parâmetros encerrada");
			}
		}
	}

	@AutorizarJob(OperacaoJob.EXECUTAR_ACAO)
	@PostMapping(path = "/jobs/{id}/actions", consumes = "application/json", produces = "application/json")
	JobDetalhadoDto executar(@PathVariable UUID id, @RequestBody String corpo) {
		AcaoJob acao = ExecutarAcaoRequisicao.deJson(corpo).acao();
		AcaoAplicada aplicada = this.service.executarAcao(id, acao);
		// Os três destinos das ações de finalização (liberado, cancelado, arquivado) são
		// terminais: emitir depois do commit fecha o stream do job, como a skill sse
		// pede.
		if (acao == AcaoJob.ACEITAR_META) {
			this.metricas.metaVendaAceita().increment();
			try (var escopo = this.correlacao.abrir(id.toString(), null)) {
				log.atInfo().log("meta sugerida aceita; resultado vigente substituído");
			}
			SimulacaoDto simulacao = aplicada.job().simulacao();
			if (simulacao != null) {
				this.emissores.emitir(id, EventoSse.de("resultado",
						new EventoResultadoDto(id, simulacao.id(), simulacao.status(), simulacao.veredito())));
			}
			this.emissores.emitir(id, EventoSse.de("estado", aplicada.evento()));
		}
		else {
			this.emissores.emitir(id, EventoSse.ultimo("estado", aplicada.evento()));
		}
		return aplicada.job();
	}

	@AutorizarJob(OperacaoJob.RENOMEAR)
	@PutMapping(path = "/jobs/{id}/nome", consumes = "application/json", produces = "application/json")
	JobDetalhadoDto renomear(@PathVariable UUID id, @RequestBody(required = false) @Nullable String corpo) {
		try (var escopo = this.correlacao.abrir(id.toString(), null)) {
			RenomearJobRequisicao requisicao;
			try {
				requisicao = RenomearJobRequisicao.deJson(corpo);
			}
			catch (RenomearJobException ex) {
				log.atWarn().addKeyValue("motivo", ex.motivo().paraLog()).log("renomeação recusada: nome inválido");
				throw ex;
			}
			JobDetalhadoDto job = this.service.renomear(id, requisicao);
			log.atInfo().log("regra renomeada");
			return job;
		}
	}

	@AutorizarJob(OperacaoJob.REPROCESSAR)
	@PostMapping(path = "/jobs/{id}/reprocessar", produces = "application/json")
	ResponseEntity<JobCriadoDto> reprocessar(@PathVariable("id") UUID id,
			@RequestBody(required = false) @Nullable String corpo) {
		JobCriadoDto job = this.service.reprocessar(id, ReprocessarJobRequisicao.deJson(corpo));
		return ResponseEntity.created(URI.create("/api/jobs/" + job.id())).body(job);
	}

}
