package synapse.api.submissoes;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import java.util.function.Consumer;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.jspecify.annotations.Nullable;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.job.JobsDeSubmissoes;
import synapse.api.job.JobsDeSubmissoes.TipoEntrada;
import synapse.api.job.JobsDeSubmissoes.Rodada;
import synapse.api.submissoes.SubmissoesRepository.FinalidadeTrabalho;

@Service
class SubmissoesService {

	private final SubmissoesRepository repository;

	private final JobsDeSubmissoes jobs;

	private final DisponibilidadeTranscricao transcricao;

	SubmissoesService(SubmissoesRepository repository, JobsDeSubmissoes jobs, DisponibilidadeTranscricao transcricao) {
		this.repository = repository;
		this.jobs = jobs;
		this.transcricao = transcricao;
	}

	@Transactional
	SubmissaoCriada texto(EntradaSubmissao entrada, AcessoDoUsuario acesso, Consumer<UUID> rodadaIdentificada) {
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		UUID jobId = entrada.jobId();
		if (jobId != null) {
			var recebida = this.jobs.corrigir(jobId, TipoEntrada.TEXTO, acesso, rodada -> {
				rodadaIdentificada.accept(rodada);
				return this.repository.inserirTexto(acesso.usuarioId(), entrada.texto(), agora);
			}, agora);
			return new SubmissaoCriada(recebida.submissaoId(), "texto", "correcao", agora, recebida.job(),
					recebida.rodada());
		}
		UUID id = this.repository.inserirTexto(acesso.usuarioId(), entrada.texto(), agora);
		var job = this.jobs.criar(id, TipoEntrada.TEXTO, acesso, agora);
		return new SubmissaoCriada(id, "texto", "entrada_inicial", agora, job);
	}

	@Transactional
	SubmissaoCriada voz(EntradaSubmissao entrada, AudioSubmissao audio, AcessoDoUsuario acesso,
			Consumer<UUID> rodadaIdentificada) {
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		UUID jobId = entrada.jobId();
		if (jobId != null) {
			var recebida = this.jobs.corrigir(jobId, TipoEntrada.VOZ, acesso, rodada -> {
				rodadaIdentificada.accept(rodada);
				return this.repository.inserirVoz(acesso.usuarioId(), audio, agora);
			}, agora);
			exigirTranscricao();
			this.repository.inserirTrabalho(jobId, recebida.submissaoId(), FinalidadeTrabalho.CORRECAO, agora);
			return new SubmissaoCriada(recebida.submissaoId(), "voz", "correcao", agora, recebida.job(),
					recebida.rodada());
		}
		UUID id = this.repository.inserirVoz(acesso.usuarioId(), audio, agora);
		var job = this.jobs.criar(id, TipoEntrada.VOZ, acesso, agora);
		exigirTranscricao();
		this.repository.inserirTrabalho(job.id(), id, FinalidadeTrabalho.ENTRADA_INICIAL, agora);
		return new SubmissaoCriada(id, "voz", "entrada_inicial", agora, job);
	}

	private void exigirTranscricao() {
		if (!this.transcricao.disponivel()) {
			throw new SubmissaoException(HttpStatus.CONFLICT, "estado_invalido",
					"O envio por voz não está disponível no momento. Envie o texto.");
		}
	}

}

record SubmissaoCriada(UUID id, String tipo, String finalidade, Instant criado_em, JobsDeSubmissoes.JobCriado job,
		@JsonInclude(JsonInclude.Include.NON_NULL) @Nullable Rodada rodada) {
	SubmissaoCriada(UUID id, String tipo, String finalidade, Instant criadoEm, JobsDeSubmissoes.JobCriado job) {
		this(id, tipo, finalidade, criadoEm, job, null);
	}
}
