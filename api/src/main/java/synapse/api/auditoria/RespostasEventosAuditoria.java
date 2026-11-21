package synapse.api.auditoria;

import java.time.Instant;
import java.util.List;
import java.util.UUID;

import com.fasterxml.jackson.annotation.JsonInclude;
import org.jspecify.annotations.Nullable;

record PaginaEventosAuditoriaDto(List<EventoAuditoriaDto> itens, int pagina, int tamanho, long total,
		ContadoresEventosAuditoriaDto contadores) {
}

record ContadoresEventosAuditoriaDto(long eventos, long usuarios, long regras, long simulacoes_com_falha) {
}

record FiltrosEventosAuditoriaDto(List<String> usuarios, List<String> meses, List<String> lojas, List<String> marcas,
		List<String> cargos) {
}

record JobEventoAuditoriaDto(UUID id, @Nullable String nome, String status) {
}

@JsonInclude(JsonInclude.Include.NON_NULL)
record EventoAuditoriaDto(Instant instante, String tipo, String autor, String usuario_login, JobEventoAuditoriaDto job,
		UUID origem_id, @Nullable String loja, @Nullable String marca, @Nullable String cargo,
		@Nullable String finalidade, @Nullable String tipo_entrada, @Nullable String origem_versao,
		@Nullable Integer versao, @Nullable String status, @Nullable String veredito, @Nullable String acao) {

	EventoAuditoriaDto comNome(@Nullable String nome) {
		return new EventoAuditoriaDto(this.instante, this.tipo, this.autor, this.usuario_login,
				new JobEventoAuditoriaDto(this.job.id(), nome, this.job.status()), this.origem_id, this.loja,
				this.marca, this.cargo, this.finalidade, this.tipo_entrada, this.origem_versao, this.versao,
				this.status, this.veredito, this.acao);
	}

}
