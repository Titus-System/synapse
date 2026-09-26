package synapse.api.job;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * Cliente de teste para {@code GET /jobs/{id}/events}: lê o corpo
 * {@code text/event-stream} numa thread própria e acumula tudo num buffer, para que os
 * testes esperem por um trecho aparecer em vez de depender do enquadramento exato de cada
 * leitura de socket.
 */
final class StreamCliente {

	private final HttpResponse<InputStream> resposta;

	private final StringBuilder buffer = new StringBuilder();

	private final Object trava = new Object();

	private final Thread leitora;

	private boolean fimDoStream;

	StreamCliente(HttpResponse<InputStream> resposta) {
		this.resposta = resposta;
		this.leitora = Thread.ofVirtual().unstarted(this::ler);
		this.leitora.start();
	}

	private void ler() {
		try (BufferedReader reader = new BufferedReader(
				new InputStreamReader(this.resposta.body(), StandardCharsets.UTF_8))) {
			int caractere;
			while ((caractere = reader.read()) != -1) {
				synchronized (this.trava) {
					this.buffer.append((char) caractere);
					this.trava.notifyAll();
				}
			}
		}
		catch (IOException ex) {
			// Fechamento esperado: fechar() encerrou o corpo, ou o servidor encerrou o
			// stream (job terminal) - as duas aparecem aqui como fim de leitura.
		}
		finally {
			synchronized (this.trava) {
				this.fimDoStream = true;
				this.trava.notifyAll();
			}
		}
	}

	int status() {
		return this.resposta.statusCode();
	}

	String cabecalho(String nome) {
		return this.resposta.headers().firstValue(nome).orElse("");
	}

	String conteudo() {
		synchronized (this.trava) {
			return this.buffer.toString();
		}
	}

	/**
	 * Espera até {@code marcador} aparecer num bloco de evento **completo** (delimitado
	 * por linha em branco, como o enquadramento SSE exige) e devolve esse bloco. Esperar
	 * só pelo marcador não bastaria: ele pode aparecer no buffer antes do resto do bloco
	 * (o `id:`, que este emissor escreve antes do `event:`, ou o `data:` que vem depois)
	 * ter chegado.
	 */
	String aguardarBloco(String marcador, Duration timeout) {
		long limiteNanos = System.nanoTime() + timeout.toNanos();
		synchronized (this.trava) {
			while (true) {
				String texto = this.buffer.toString();
				int inicioMarcador = texto.indexOf(marcador);
				if (inicioMarcador >= 0) {
					int fimBloco = texto.indexOf("\n\n", inicioMarcador);
					if (fimBloco >= 0 || this.fimDoStream) {
						int inicioAnterior = texto.lastIndexOf("\n\n", inicioMarcador);
						int inicioBloco = (inicioAnterior >= 0) ? inicioAnterior + 2 : 0;
						return (fimBloco >= 0) ? texto.substring(inicioBloco, fimBloco) : texto.substring(inicioBloco);
					}
				}
				long restanteMs = (limiteNanos - System.nanoTime()) / 1_000_000;
				if (restanteMs <= 0) {
					throw new AssertionError("timeout esperando o bloco de \"%s\" completar; recebido até agora: %s"
						.formatted(marcador, texto));
				}
				try {
					this.trava.wait(restanteMs);
				}
				catch (InterruptedException ex) {
					Thread.currentThread().interrupt();
					throw new AssertionError(ex);
				}
			}
		}
	}

	int contarOcorrencias(String trecho) {
		String texto = conteudo();
		int contagem = 0;
		int indice = 0;
		while ((indice = texto.indexOf(trecho, indice)) != -1) {
			contagem++;
			indice += trecho.length();
		}
		return contagem;
	}

	/**
	 * Espera o servidor encerrar o stream (EOF), como acontece após um evento terminal.
	 */
	void aguardarFimDoStream(Duration timeout) {
		long limiteNanos = System.nanoTime() + timeout.toNanos();
		synchronized (this.trava) {
			while (!this.fimDoStream) {
				long restanteMs = (limiteNanos - System.nanoTime()) / 1_000_000;
				if (restanteMs <= 0) {
					throw new AssertionError("timeout esperando o servidor encerrar o stream");
				}
				try {
					this.trava.wait(restanteMs);
				}
				catch (InterruptedException ex) {
					Thread.currentThread().interrupt();
					throw new AssertionError(ex);
				}
			}
		}
	}

	void fechar() {
		try {
			this.resposta.body().close();
		}
		catch (IOException ignorada) {
			// Encerramento do lado do cliente; não há o que fazer com uma falha aqui.
		}
	}

}
