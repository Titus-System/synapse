#!/usr/bin/env sh
#
# Despacha a verificacao (verify.sh) dos componentes tocados por uma lista de
# caminhos alterados. E o mesmo script reutilizado pelo hook de pre-commit
# (.githooks/pre-commit) e pela CI (T-017) — o despacho existe uma unica vez
# aqui para que hook e CI nunca divirjam.
#
# Uso: despachar-verificacao.sh <caminho> [<caminho> ...]
#
# Regras (ADR-002 — um servico por PR; verificacao despachada por caminho):
#   - Alteracao restrita a um componente roda somente o verify.sh daquele
#     componente.
#   - Alteracao em contracts/ roda os quatro verify.sh, porque e o teste de
#     que o schema novo nao quebra quem ja consome.
#   - Alteracao em dois ou mais componentes, sem tocar contracts/, e
#     recusada: o commit deve ficar restrito a um componente.

set -eu

diretorio_do_script="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
raiz_do_repo="$(CDPATH= cd -- "$diretorio_do_script/.." && pwd)"

componentes="frontend api codegen worker"

contratos_tocados=0
componentes_tocados=""

for caminho in "$@"; do
	case "$caminho" in
	contracts/*)
		contratos_tocados=1
		;;
	esac
	for componente in $componentes; do
		case "$caminho" in
		"$componente"/*)
			case " $componentes_tocados " in
			*" $componente "*) ;;
			*) componentes_tocados="$componentes_tocados $componente" ;;
			esac
			;;
		esac
	done
done

componentes_tocados="$(printf '%s' "$componentes_tocados" | sed 's/^ *//')"

rodar_verificacao() {
	componente="$1"
	echo "==> Verificando $componente"
	"$raiz_do_repo/$componente/verify.sh"
}

if [ "$contratos_tocados" -eq 1 ]; then
	echo "contracts/ alterado: rodando a verificacao dos quatro componentes."
	for componente in $componentes; do
		rodar_verificacao "$componente"
	done
	exit 0
fi

quantidade_de_componentes=0
for componente in $componentes_tocados; do
	quantidade_de_componentes=$((quantidade_de_componentes + 1))
done

if [ "$quantidade_de_componentes" -eq 0 ]; then
	echo "Nenhum componente tocado (frontend, api, codegen, worker ou contracts). Nada a verificar."
	exit 0
fi

if [ "$quantidade_de_componentes" -gt 1 ]; then
	echo "Commit recusado: toca mais de um componente sem alterar contracts/." >&2
	echo "Componentes tocados:$(printf ' %s' "$componentes_tocados")" >&2
	echo "Mantenha um servico por PR (ADR-002): separe em commits/PRs distintos." >&2
	exit 1
fi

rodar_verificacao "$componentes_tocados"
