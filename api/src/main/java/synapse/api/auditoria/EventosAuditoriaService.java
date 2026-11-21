package synapse.api.auditoria;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.job.NomesDeJobs;

@Service
class EventosAuditoriaService {

	private final EventosAuditoriaRepository repository;

	private final NomesDeJobs nomes;

	EventosAuditoriaService(EventosAuditoriaRepository repository, NomesDeJobs nomes) {
		this.repository = repository;
		this.nomes = nomes;
	}

	@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
	PaginaEventosAuditoriaDto listar(ConsultaEventosAuditoria consulta, PaginaAuditoria pagina) {
		ContadoresEventosAuditoriaDto contadores = this.repository.contar(consulta);
		List<EventoAuditoriaDto> eventos = this.repository.listar(consulta, pagina);
		List<UUID> jobs = eventos.stream().map(evento -> evento.job().id()).distinct().toList();
		Map<UUID, String> nomesResolvidos = this.nomes.resolver(jobs);
		List<EventoAuditoriaDto> itens = eventos.stream()
			.map(evento -> evento.comNome(nomesResolvidos.get(evento.job().id())))
			.toList();
		return new PaginaEventosAuditoriaDto(itens, pagina.pagina(), pagina.tamanho(), contadores.eventos(),
				contadores);
	}

	@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
	FiltrosEventosAuditoriaDto consultarFiltros() {
		return this.repository.consultarFiltros();
	}

}
