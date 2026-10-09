package synapse.api.submissoes;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.security.AcessoDoUsuario;
import synapse.api.job.JobsDeSubmissoes;
import synapse.api.job.JobsDeSubmissoes.TipoEntrada;

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
	SubmissaoCriada texto(EntradaSubmissao entrada, AcessoDoUsuario acesso) {
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		UUID id = this.repository.inserirTexto(acesso.usuarioId(), entrada.texto(), agora);
		var job = this.jobs.criar(id, TipoEntrada.TEXTO, entrada.parametros(), acesso, agora);
		return new SubmissaoCriada(id, "texto", "entrada_inicial", agora, job);
	}

	@Transactional
	SubmissaoCriada voz(EntradaSubmissao entrada, AudioSubmissao audio, AcessoDoUsuario acesso) {
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		UUID id = this.repository.inserirVoz(acesso.usuarioId(), audio, agora);
		var job = this.jobs.criar(id, TipoEntrada.VOZ, entrada.parametros(), acesso, agora);
		if (!this.transcricao.disponivel()) {
			throw new SubmissaoException(HttpStatus.CONFLICT, "estado_invalido",
					"O envio por voz não está disponível no momento. Envie o texto.");
		}
		this.repository.inserirTrabalho(job.id(), id, agora);
		return new SubmissaoCriada(id, "voz", "entrada_inicial", agora, job);
	}

}

record SubmissaoCriada(UUID id, String tipo, String finalidade, Instant criado_em, JobsDeSubmissoes.JobCriado job) {
}
