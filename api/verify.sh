#!/usr/bin/env sh

set -eu

diretorio_do_script="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$diretorio_do_script"

./mvnw spring-javaformat:validate
./mvnw -DskipTests compile
./mvnw test
