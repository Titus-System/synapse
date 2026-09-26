#!/usr/bin/env sh

set -eu

diretorio_do_script="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$diretorio_do_script"

# O projeto exige Java 21
if [ -z "${JAVA_HOME:-}" ]; then
	jdk21="$(ls -d /usr/lib/jvm/java-21-openjdk-* 2>/dev/null | head -n 1)"
	if [ -n "$jdk21" ]; then
		JAVA_HOME="$jdk21"
		export JAVA_HOME
	fi
fi

./mvnw spring-javaformat:validate
./mvnw -DskipTests compile
./mvnw test
