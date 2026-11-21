package synapse.api.auditoria;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.auditoria.ResumoAuditoriaRepository.AlteracaoLida;
import synapse.api.auditoria.ResumoAuditoriaRepository.SimulacaoLida;

/**
 * O resumo do dossiê com os números prontos para exibir. As consultas rodam numa
 * transação só de leitura e com um único instantâneo do banco, como as de
 * {@link AuditoriaService}.
 */
@Service
class ResumoAuditoriaService {

	private static final String SUCESSO = "sucesso";

	private final AuditoriaRepository auditoria;

	private final ResumoAuditoriaRepository repository;

	ResumoAuditoriaService(AuditoriaRepository auditoria, ResumoAuditoriaRepository repository) {
		this.auditoria = auditoria;
		this.repository = repository;
	}

	@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
	ResumoDossieAuditoriaDto consultar(UUID jobId) {
		if (!this.auditoria.existeJob(jobId)) {
			throw new JobNaoEncontradoNaAuditoriaException();
		}
		List<SimulacaoLida> simulacoes = this.repository.listarSimulacoes(jobId);
		return new ResumoDossieAuditoriaDto(contar(simulacoes), versaoVigente(simulacoes), versoes(jobId),
				comparar(simulacoes));
	}

	private static ContagemSimulacoesDto contar(List<SimulacaoLida> simulacoes) {
		long sucesso = simulacoes.stream().filter(simulacao -> SUCESSO.equals(simulacao.status())).count();
		long concluidas = simulacoes.stream().filter(simulacao -> simulacao.status() != null).count();
		return new ContagemSimulacoesDto(simulacoes.size(), sucesso, concluidas - sucesso);
	}

	/**
	 * A versão da simulação vigente, a última com resultado, como em {@code GET
	 * /jobs/{id}}.
	 */
	private static @Nullable Integer versaoVigente(List<SimulacaoLida> simulacoes) {
		Integer vigente = null;
		for (SimulacaoLida simulacao : simulacoes) {
			if (simulacao.resultadoId() != null) {
				vigente = simulacao.versao();
			}
		}
		return vigente;
	}

	private List<VersaoResumoAuditoriaDto> versoes(UUID jobId) {
		Map<UUID, List<AlteracaoVersaoDto>> porVersao = new HashMap<>();
		for (AlteracaoLida lida : this.repository.listarAlteracoes(jobId)) {
			porVersao.computeIfAbsent(lida.regraId(), id -> new ArrayList<>()).add(lida.alteracao());
		}
		return this.repository.listarVersoes(jobId)
			.stream()
			.map(versao -> new VersaoResumoAuditoriaDto(versao.id(), versao.numero(), versao.regraOrigemId(),
					List.copyOf(porVersao.getOrDefault(versao.id(), List.of()))))
			.toList();
	}

	/**
	 * Cada simulação com {@code sucesso} contra a anterior com {@code sucesso}, pela
	 * ordem de criação. Os quatro totais obrigatórios existem em todo resultado com
	 * {@code sucesso}.
	 */
	private static List<ComparacaoSimulacaoDto> comparar(List<SimulacaoLida> simulacoes) {
		List<ComparacaoSimulacaoDto> comparacoes = new ArrayList<>();
		SimulacaoLida anterior = null;
		for (SimulacaoLida atual : simulacoes) {
			if (!SUCESSO.equals(atual.status())) {
				continue;
			}
			if (anterior != null) {
				comparacoes.add(new ComparacaoSimulacaoDto(Objects.requireNonNull(atual.resultadoId()),
						Objects.requireNonNull(anterior.resultadoId()),
						VariacaoDto.entre(Objects.requireNonNull(anterior.baseline()),
								Objects.requireNonNull(atual.baseline())),
						VariacaoDto.entre(Objects.requireNonNull(anterior.simulado()),
								Objects.requireNonNull(atual.simulado())),
						VariacaoDto.entre(Objects.requireNonNull(anterior.diferencaAbs()),
								Objects.requireNonNull(atual.diferencaAbs())),
						VariacaoDto.entre(Objects.requireNonNull(anterior.diferencaPct()),
								Objects.requireNonNull(atual.diferencaPct())),
						VariacaoDto.entreOpcionais(anterior.orcamento(), atual.orcamento()),
						VariacaoDto.entreOpcionais(anterior.metaVenda(), atual.metaVenda())));
			}
			anterior = atual;
		}
		return List.copyOf(comparacoes);
	}

}
