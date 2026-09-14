#!/usr/bin/env sh

set -eu

diretorio_do_script="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$diretorio_do_script"

npm run type-check
npm run lint:verificar
npm run test:unit -- --run
npm run build-only
