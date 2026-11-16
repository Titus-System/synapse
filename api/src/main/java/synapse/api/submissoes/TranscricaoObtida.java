package synapse.api.submissoes;

import org.jspecify.annotations.Nullable;

/** O texto devolvido pelo provedor e o modelo que o transcreveu, gravados juntos. */
record TranscricaoObtida(String texto, ModeloTranscricao modelo) {
}

/** O formato de {@code submissoes.transcricao_modelo}. */
record ModeloTranscricao(String provedor, String modelo, @Nullable String versao) {
}
