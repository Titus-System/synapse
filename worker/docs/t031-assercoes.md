# T-031 — Asserções ao finalizar a apuração

`app/sandbox/assercoes.py` verifica três invariantes sem ler arquivos, consultar
baseline, acessar rede ou receber orçamento. A decisão do Scrum Master de
15/09/2026 foi aplicada: comissão positiva exige **origem válida e rastreável**,
que pode ser venda, evento remunerado de RH ou bônus da competência.

| Nome no contrato existente | Verificação |
| --- | --- |
| `sem_comissao_negativa` | Valores finitos e não negativos; bool, NaN e infinito são inválidos. |
| `sem_comissao_sem_venda` | Confere referências com as entradas: matrícula e competência, venda própria ou da loja para cargo 150, evento de afastamento remunerado ou direito a bônus. Uma etiqueta de regra sozinha não é origem. |
| `soma_loja_igual_soma_matricula` | Compara as linhas por matrícula com o acumulador por loja produzido durante o cálculo, incluindo identidade da loja, chaves ausentes e matrículas duplicadas. Usa Decimal, sem tolerância que esconda centavos. |

A loja da comissão é a lotação no RH, como na T-030. Vendas de vendedores em
outras lojas continuam ligadas à matrícula; gerente usa vendas da própria loja.
Referências de linha começam em 1 e apontam para a tabela completa recebida pela
função, antes do filtro de competência. Não reordenar/filtrar a entrada e depois
reutilizar referências antigas.

## Integração e saída

`regras_base.apurar(...)` chama `finalizar_apuracao` obrigatoriamente ao fim do
cálculo. Mantém a interface existente: listas continuam listas (`TabelaApurada`);
DataFrame-like continua da mesma classe. O resultado inclui `cod_loja`, evitando
usar a descrição como chave de agregação.

- Lista: `tabela.resultado_apuracao`.
- Pandas: `tabela.attrs["resultado_apuracao"]`.
- Outros DataFrame-like sem `attrs`: `tabela.resultado_apuracao`.

O desfecho interno tem `status`, `competencia`, `assercoes`, `total`, `por_loja`,
`por_matricula` e `veredito: null`. As três asserções são avaliadas mesmo quando
uma falha. Cada falha identifica competência, linha/matrícula ou loja.

Falha retorna `status: assercao_violada`, totais e quebras nulos.
`apurar` levanta `AssercaoVioladaError`, cujo atributo `resultado` conserva esse
desfecho serializável. Portanto, quem chama não recebe uma tabela inválida como
sucesso. Isso é falha de cálculo/código, não `inviavel`; orçamento e veredito
permanecem fora do sandbox.

As entradas de `assercoes` seguem o JSON Schema já existente em
`contracts/domain/resultado-assercoes.schema.json`, sem alterar contratos públicos.
O envelope interno por competência **não** substitui o resultado agregado do job
(`resultado-simulacao.schema.json`). A T-065 deve consolidar uma entrada por
invariante no período e propagar qualquer falha como terminal, sem retry de infra.

## Limite desta entrega

No snapshot fornecido, o consumidor apenas prepara o payload: o executor do
container ainda não existe. O futuro executor deve chamar `finalizar_apuracao`
**dentro do sandbox**, depois de qualquer apuração gerada, passando as entradas
originais e o acumulador independente de lojas. Não validar antes da regra e
aceitar alterações posteriores. Nunca executar código gerado no processo do worker.

T-031 não inicia containers, não muda RabbitMQ, não publica resultado e não
implementa T-065/T-066. O motor base já executa a validação automaticamente.
As asserções detectam inconsistências internas; não provam que o percentual ou
todas as regras de negócio estejam corretos (cobertura de regras é T-056).

## Verificação

Na pasta `worker/`:

```bash
poetry run pytest tests/app/sandbox/test_assercoes.py tests/app/sandbox/test_regras_base.py
sh verify.sh
```

Os testes injetam cada violação, referências falsas, troca de loja com total
preservado e duplicidade. Também cobrem piso sem venda e gerente sem venda própria.
