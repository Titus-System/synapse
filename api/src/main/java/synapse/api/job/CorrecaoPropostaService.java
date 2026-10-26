package synapse.api.job;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

import org.jspecify.annotations.Nullable;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import synapse.api.core.outbox.EventoOutbox;
import synapse.api.core.outbox.Outbox;
import synapse.api.job.JobRepository.ContextoDoJob;

@Service
class CorrecaoPropostaService {

	private static final JsonMapper JSON = JsonMapper.builder()
		.enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
		.build();

	private final JobRepository repository;

	private final RodadasCorrecaoRepository tentativas;

	private final RodadasRepository rodadas;

	private final VersoesDaRegra versoes;

	private final MaquinaDeEstadosDoJob maquina;

	private final Outbox outbox;

	CorrecaoPropostaService(JobRepository repository, RodadasCorrecaoRepository tentativas, RodadasRepository rodadas,
			VersoesDaRegra versoes, MaquinaDeEstadosDoJob maquina, Outbox outbox) {
		this.repository = repository;
		this.tentativas = tentativas;
		this.rodadas = rodadas;
		this.versoes = versoes;
		this.maquina = maquina;
		this.outbox = outbox;
	}

	@Transactional
	CorrecaoAplicada aplicar(CorrecaoPropostaDto evento) {
		UUID jobId = evento.job_id();
		var contextos = this.repository.buscarContextoComTrava(jobId);
		if (contextos.isEmpty()) {
			return new CorrecaoAplicada("descartada", null, null, "job_desconhecido");
		}
		ContextoDoJob contexto = contextos.getFirst();
		var encontradas = this.tentativas.buscarPorSubmissao(jobId, evento.submissao_id());
		if (encontradas.size() != 1)
			return new CorrecaoAplicada("descartada", null, null, "tentativa_desconhecida");
		var rodada = encontradas.getFirst();
		if (!rodada.regraId().equals(evento.regra_origem_id()))
			return new CorrecaoAplicada("descartada", null, rodada.id(), "origem_divergente");
		if ("reextracao_falhou".equals(rodada.estado())) {
			boolean duplicada = equivalentes(rodada.propostaNaoAplicada(), evento.corpo());
			return new CorrecaoAplicada(duplicada ? "duplicada" : "descartada", rodada.regraId(), rodada.id(),
					duplicada ? "proposta_ja_processada" : "tentativa_encerrada");
		}
		var parametrosOrigem = this.repository.buscarParametrosDaVersao(jobId, evento.regra_origem_id());
		if (parametrosOrigem.isEmpty())
			return new CorrecaoAplicada("descartada", null, rodada.id(), "origem_desconhecida");
		JsonNode recebidos = evento.parametros();
		String parametrosJson = recebidos == null ? parametrosOrigem.getFirst() : recebidos.toString();
		ParametrosDaSimulacao parametros = ParametrosExtraidos.deVersaoExistente(parametrosJson);
		RepresentacaoRegraDto representacao = Objects
			.requireNonNull(RepresentacaoExtraida.validada(evento.representacao().toString()));
		String hash = HashDaRegra.calcular(representacao, parametros);
		var existentes = this.repository.buscarRegraPorHash(jobId, hash);
		if ("corrigida".equals(rodada.estado())) {
			boolean duplicada = !existentes.isEmpty() && existentes.getFirst().id().equals(rodada.resultanteId())
					&& "correcao".equals(existentes.getFirst().origem())
					&& mesmosArtefatos(existentes.getFirst().id(), evento.representacao(), parametrosJson);
			return new CorrecaoAplicada(duplicada ? "duplicada" : "descartada", rodada.resultanteId(), rodada.id(),
					duplicada ? "proposta_ja_aplicada" : "tentativa_encerrada");
		}
		var anteriores = this.repository.buscarUltimaVersao(jobId);
		if (contexto.status() != JobStatus.AGUARDANDO_CONFIRMACAO_PARAMETROS || anteriores.isEmpty())
			return new CorrecaoAplicada("descartada", null, rodada.id(), "job_incompativel");
		var anterior = anteriores.getFirst();
		var abertas = this.rodadas.abertas(jobId);
		if (!"em_reextracao".equals(rodada.estado()) || !rodada.regraId().equals(evento.regra_origem_id())
				|| !anterior.id().equals(evento.regra_origem_id()) || abertas.size() != 1
				|| !abertas.getFirst().id().equals(rodada.id())) {
			return new CorrecaoAplicada("descartada", null, rodada.id(), "tentativa_obsoleta");
		}
		Instant agora = Instant.now().truncatedTo(ChronoUnit.MICROS);
		Timestamp timestamp = Timestamp.from(agora);
		if (!existentes.isEmpty()) {
			UUID existente = existentes.getFirst().id();
			boolean mesmos = mesmosArtefatos(existente, evento.representacao(), parametrosJson);
			this.tentativas.fecharProposta(jobId, rodada.id(), evento.submissao_id(), evento.corpo(), timestamp);
			this.tentativas.inserirPendente(jobId, rodada.regraId(), rodada.conflitos(), rodada.id(), timestamp);
			return new CorrecaoAplicada(mesmos ? "sem_alteracao" : "bloqueada", existente, rodada.id(),
					mesmos ? "versao_existente" : "colisao_de_artefatos");
		}
		var versao = this.versoes.resolver(jobId, evento.representacao(), parametrosJson, hash, anterior.id(),
				timestamp, agora);
		if (recebidos != null)
			this.repository.substituirParametros(jobId, Objects.requireNonNull(parametros));
		ContextoDoJob efetivo = this.repository.buscarContextoComTrava(jobId).getFirst();
		List<String> campos = parametrosCorrigidos(contexto, efetivo);
		this.maquina.transicionar(jobId, JobStatus.GERANDO_REGRA, "evento", "correcao_aplicada");
		TrilhaDaConfirmacao.registrar(this.repository, jobId, versao.id(), true, representacao, anterior, campos,
				timestamp);
		this.outbox.registrar(jobId, EventoOutbox.PARAMETROS_CONFIRMADOS, new ParametrosConfirmadosDto(jobId,
				versao.id(), efetivo.competencias(), efetivo.orcamento(), efetivo.metaVenda()));
		this.rodadas.corrigir(jobId, rodada.id(), anterior.id(), versao.id(), agora);
		return new CorrecaoAplicada("aplicada", versao.id(), rodada.id(), "nova_versao");
	}

	private boolean mesmosArtefatos(UUID regraId, JsonNode representacao, @Nullable String parametrosJson) {
		String existentes = this.repository.buscarParametrosDaVersao(regraId).getFirst();
		return equivalentes(this.repository.buscarRepresentacaoCompleta(regraId), representacao)
				&& equivalentes(parametrosComparaveis(existentes), parametrosComparaveis(parametrosJson));
	}

	private static @Nullable JsonNode parametrosComparaveis(@Nullable String json) {
		JsonNode parametros = arvore(json);
		if (parametros instanceof tools.jackson.databind.node.ObjectNode objeto
				&& objeto.path("competencias").isArray()) {
			var competencias = new java.util.TreeSet<String>();
			objeto.path("competencias").forEach(valor -> competencias.add(valor.asString()));
			var ordenadas = objeto.putArray("competencias");
			competencias.forEach(ordenadas::add);
		}
		return parametros;
	}

	private static boolean equivalentes(@Nullable JsonNode a, @Nullable JsonNode b) {
		if (a == null || b == null)
			return a == b;
		if (a.isNumber() && b.isNumber())
			return a.decimalValue().compareTo(b.decimalValue()) == 0;
		if (a.isObject() && b.isObject()) {
			if (a.size() != b.size())
				return false;
			for (String campo : a.propertyNames()) {
				if (!equivalentes(a.get(campo), b.get(campo)))
					return false;
			}
			return true;
		}
		if (a.isArray() && b.isArray()) {
			if (a.size() != b.size())
				return false;
			for (int i = 0; i < a.size(); i++) {
				if (!equivalentes(a.get(i), b.get(i)))
					return false;
			}
			return true;
		}
		return a.equals(b);
	}

	private static @Nullable JsonNode arvore(@Nullable String json) {
		return json == null ? null : JSON.readTree(json);
	}

	private static List<String> parametrosCorrigidos(ContextoDoJob anterior, ContextoDoJob atual) {
		List<String> campos = new ArrayList<>();
		if (TrilhaDaConfirmacao.decimalDiferente(anterior.orcamento(), atual.orcamento()))
			campos.add("parametros.orcamento");
		if (TrilhaDaConfirmacao.decimalDiferente(anterior.metaVenda(), atual.metaVenda()))
			campos.add("parametros.meta_venda");
		if (!anterior.competencias().equals(atual.competencias()))
			campos.add("parametros.competencias");
		return campos;
	}

	record CorrecaoAplicada(String resultado, @Nullable UUID regraId, @Nullable UUID rodadaId, String motivo) {
	}

}
