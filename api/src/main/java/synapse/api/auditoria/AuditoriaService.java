package synapse.api.auditoria;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.auditoria.AuditoriaRepository.JobLido;
import synapse.api.job.NomesDeJobs;

/**
 * As consultas de uma resposta rodam numa transação só de leitura e com um único
 * instantâneo do banco, para que uma seção não aponte o que outra, lida antes, ainda não
 * tinha enquanto o job avança.
 */
@Service
class AuditoriaService {

	private final AuditoriaRepository repository;

	private final NomesDeJobs nomes;

	AuditoriaService(AuditoriaRepository repository, NomesDeJobs nomes) {
		this.repository = repository;
		this.nomes = nomes;
	}

	@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
	PaginaJobsAuditoriaDto listar(PaginaAuditoria pagina) {
		long total = this.repository.contarJobs();
		List<JobAuditoriaDto> jobs = this.repository.listarJobs(pagina.tamanho(), pagina.deslocamento())
			.stream()
			.map(JobLido::job)
			.toList();
		Map<UUID, String> nomesResolvidos = this.nomes.resolver(jobs.stream().map(JobAuditoriaDto::id).toList());
		List<JobAuditoriaDto> itens = jobs.stream().map(job -> job.comNome(nomesResolvidos.get(job.id()))).toList();
		return new PaginaJobsAuditoriaDto(itens, pagina.pagina(), pagina.tamanho(), total);
	}

	@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
	RegistroAuditoriaDto consultar(UUID jobId) {
		List<JobLido> encontrados = this.repository.buscarJob(jobId);
		if (encontrados.isEmpty()) {
			throw new JobNaoEncontradoNaAuditoriaException();
		}
		JobLido lido = encontrados.getFirst();
		JobAuditoriaDto job = lido.job().comNome(this.nomes.resolver(List.of(jobId)).get(jobId));
		return new RegistroAuditoriaDto(new JobRegistradoDto(job, lido.iniciadoEm()),
				this.repository.listarEntradas(jobId), this.repository.listarVersoes(jobId),
				this.repository.listarEtapas(jobId), this.repository.listarChamadasModelo(jobId),
				this.repository.listarCodigos(jobId), this.repository.listarResultados(jobId),
				this.repository.listarSimulacoes(jobId), this.repository.listarTransicoes(jobId),
				this.repository.listarAcoes(jobId), this.repository.listarRodadas(jobId),
				this.repository.listarSugestoesMeta(jobId), this.repository.listarExplicacoes(jobId));
	}

}
