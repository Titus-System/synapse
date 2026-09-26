package synapse.api.job;

/**
 * Corpo de erro conforme {@code components/schemas/Erro} do contrato HTTP: {@code codigo}
 * é o que o cliente decide em cima, {@code mensagem} é texto que o domínio decidiu expor
 * - nunca detalhe interno.
 */
record ErroDto(String codigo, String mensagem) {
}
