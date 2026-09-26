package synapse.api.core.config;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Stream;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class NoDirectEnvironmentAccessTests {

	@Test
	void mainSourcesDoNotReadTheEnvironmentDirectly() throws IOException {
		try (Stream<Path> sources = Files.walk(Path.of("src/main/java"))) {
			List<Path> offenders = sources.filter((path) -> path.toString().endsWith(".java"))
				.filter(NoDirectEnvironmentAccessTests::callsSystemGetenv)
				.toList();

			assertThat(offenders)
				.as("o .env entra por spring.config.import em application.yaml e sai pelo Environment do Spring; "
						+ "System.getenv escapa desse ponto único")
				.isEmpty();
		}
	}

	private static boolean callsSystemGetenv(Path source) {
		try {
			return Files.readString(source).contains("System.getenv");
		}
		catch (IOException ex) {
			throw new UncheckedIOException(ex);
		}
	}

}
