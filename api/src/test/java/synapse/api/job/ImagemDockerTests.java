package synapse.api.job;

import java.util.Arrays;
import java.util.Optional;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIf;
import org.testcontainers.DockerClientFactory;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Protege o gate dos testes fim a fim. Um gate que responde "existe" para tudo não pula
 * nada: a CI tenta baixar uma imagem que só existe na máquina de quem a construiu, e o
 * build quebra por um motivo que não tem relação com a mudança - foi exatamente o que
 * aconteceu.
 */
@EnabledIf("dockerDisponivel")
class ImagemDockerTests {

	static boolean dockerDisponivel() {
		return DockerClientFactory.instance().isDockerAvailable();
	}

	/**
	 * O caso que quebrou: a etiqueta não existe e o gate precisa dizer que não existe.
	 * Não depende de imagem nenhuma estar presente, então vale em qualquer máquina.
	 */
	@Test
	void recusaUmaEtiquetaQueNaoExiste() {
		assertThat(ImagemDocker.existe("synapse-imagem-que-nao-existe:jamais")).isFalse();
	}

	/**
	 * O contraponto, para o gate não passar simplesmente respondendo "não" para tudo. Usa
	 * uma imagem qualquer já presente no daemon, em vez de uma fixa: numa máquina limpa
	 * não há garantia de que uma etiqueta específica tenha sido baixada.
	 */
	@Test
	void reconheceUmaImagemPresenteNoDaemon() {
		Optional<String> presente = DockerClientFactory.instance()
			.client()
			.listImagesCmd()
			.exec()
			.stream()
			.map(imagem -> imagem.getRepoTags())
			.filter(etiquetas -> etiquetas != null)
			.flatMap(Arrays::stream)
			.filter(etiqueta -> !etiqueta.contains("<none>"))
			.findFirst();
		assumeTrue(presente.isPresent(), "nenhuma imagem local para conferir o caso positivo");

		assertThat(ImagemDocker.existe(presente.get())).isTrue();
	}

}
