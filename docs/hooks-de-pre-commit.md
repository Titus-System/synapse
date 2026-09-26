# Hook de pré-commit

O Synapse é um monorepo com quatro componentes (`frontend`, `api`, `codegen`, `worker`), cada um com seu próprio `verify.sh` (ver [ADR-002](adrs/ADR-002.md)). Rodar os quatro a cada commit tornaria o commit lento o bastante para o time contornar o hook, então o hook de pré-commit despacha apenas os `verify.sh` dos componentes que o commit realmente toca.

O despacho mora em [`.githooks/despachar-verificacao.sh`](../.githooks/despachar-verificacao.sh) e é reutilizado pela CI (T-017): o hook chama esse script passando os caminhos em stage; a CI chama o mesmo script passando os caminhos do evento do GitHub. O despacho existe uma única vez — se fosse reimplementado na CI, hook e CI poderiam divergir e o feedback local deixaria de ser confiável.

## Regras de despacho

- Commit restrito a um componente → roda só o `verify.sh` daquele componente.
- Commit que toca `contracts/` → roda os quatro `verify.sh`, porque é o teste de que o schema novo não quebra quem já consome.
- Commit que toca dois ou mais componentes (`frontend`, `api`, `codegen`, `worker`) sem tocar `contracts/` → é **recusado**, com os componentes tocados nomeados na saída. Um serviço por PR (ADR-002): separe em commits ou PRs distintos.
- Commit que não toca nenhum componente nem `contracts/` (ex.: só `docs/`) → nada é verificado.

## Instalação

O hook **não se instala sozinho** ao clonar o repositório — é preciso apontar o Git para o diretório `.githooks/` uma vez, por clone:

```bash
git config core.hooksPath .githooks
```

A partir daí, todo `git commit` roda o despacho automaticamente antes de concluir o commit.

Para desinstalar (voltar ao hook padrão do Git):

```bash
git config --unset core.hooksPath
```

## Por que este hook não é o portão definitivo

O hook é **contornável** — `git commit --no-verify` pula qualquer hook local — e, como não se instala sozinho, quem nunca rodou o comando acima nunca o executa. Ele existe para dar feedback rápido a quem o instalou, não para garantir que nenhum código quebrado chegue ao repositório.

O portão real é a **CI**: o workflow que roda em cada Pull Request usa o mesmo `.githooks/despachar-verificacao.sh`, mas nenhum push ou commit local depende dele estar instalado. Só o check agregado da CI, verde, autoriza o merge.

## Chamando o despacho diretamente

Para depurar ou reproduzir o que a CI vai rodar, chame o script passando a lista de caminhos alterados, sem depender do Git:

```bash
.githooks/despachar-verificacao.sh frontend/src/App.vue frontend/package.json
```

Isso é o que permite à CI (T-017) reutilizar o script recebendo a lista de arquivos do evento do GitHub em vez de reimplementar o despacho.
