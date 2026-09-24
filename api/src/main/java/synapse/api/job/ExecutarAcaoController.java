package synapse.api.job;

import java.util.UUID;

import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import synapse.api.core.sse.EmissoresSse;
import synapse.api.core.sse.EventoSse;
import synapse.api.core.security.UsuarioAtual;
import synapse.api.job.ExecutarAcaoService.AcaoAplicada;

@RestController
class ExecutarAcaoController {

	private final ExecutarAcaoService service;

	private final EmissoresSse emissores;

	private final AutorizadorDeJob autorizador;

	private final UsuarioAtual usuarioAtual;

	ExecutarAcaoController(ExecutarAcaoService service, EmissoresSse emissores, AutorizadorDeJob autorizador,
			UsuarioAtual usuarioAtual) {
		this.service = service;
		this.emissores = emissores;
		this.autorizador = autorizador;
		this.usuarioAtual = usuarioAtual;
	}

	@PostMapping(path = "/jobs/{id}/actions", consumes = "application/json", produces = "application/json")
	JobDetalhadoDto executar(@PathVariable UUID id, @RequestBody String corpo) {
		this.autorizador.exigirAcesso(id, this.usuarioAtual.obter());
		AcaoJob acao = ExecutarAcaoRequisicao.deJson(corpo).acao();
		AcaoAplicada aplicada = this.service.aplicar(id, acao);
		// Os três destinos das ações de finalização (liberado, cancelado, arquivado) são
		// terminais: emitir depois do commit fecha o stream do job, como a skill sse
		// pede.
		this.emissores.emitir(id, EventoSse.ultimo("estado", aplicada.evento()));
		return aplicada.job();
	}

}
