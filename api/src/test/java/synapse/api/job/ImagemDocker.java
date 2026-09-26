package synapse.api.job;

import com.github.dockerjava.api.exception.NotFoundException;
import org.testcontainers.DockerClientFactory;

/**
 * Se uma imagem existe no daemon local. É o que decide se um teste fim a fim roda ou é
 * pulado, e por isso vive num lugar só: as três classes tinham a própria cópia, e o
 * defeito que isso escondeu quebrou a CI.
 * <p>
 * Usa {@code inspectImageCmd}, e não {@code listImagesCmd().withImageNameFilter(...)}: o
 * filtro por nome é ignorado pelo daemon, que devolve a lista inteira de imagens para
 * qualquer etiqueta - inclusive uma que não existe. Quem checasse a lista vazia acharia
 * que tudo existe em qualquer máquina que já tenha baixado uma imagem.
 */
final class ImagemDocker {

	private ImagemDocker() {
	}

	static boolean existe(String etiqueta) {
		try {
			DockerClientFactory.instance().client().inspectImageCmd(etiqueta).exec();
			return true;
		}
		catch (NotFoundException ausente) {
			return false;
		}
		catch (RuntimeException indisponivel) {
			// Sem daemon alcançável não há como afirmar que a imagem existe; o teste é
			// pulado
			// pelo mesmo caminho que trataria a ausência dela.
			return false;
		}
	}

}
