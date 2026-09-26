MVN := ./mvnw
JAR := target/api-0.0.1-SNAPSHOT.jar

# The project targets Java 21, but the default `java` on PATH may be older.
# When JAVA_HOME is unset, point Maven at a locally installed JDK 21.
ifeq ($(strip $(JAVA_HOME)),)
JDK21 := $(firstword $(wildcard /usr/lib/jvm/java-21-openjdk-*))
ifneq ($(JDK21),)
export JAVA_HOME := $(JDK21)
endif
endif

.DEFAULT_GOAL := help
.PHONY: help run test build package jar clean deps fmt lint check pre-commit

help: ## Show the available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

run: ## Start the application
	$(MVN) spring-boot:run

test: ## Run the tests
	$(MVN) test

build: ## Compile without running tests
	$(MVN) -DskipTests compile

fmt: ## Reformat the sources in place
	$(MVN) spring-javaformat:apply

lint: ## Check formatting and run Error Prone / NullAway
	$(MVN) spring-javaformat:validate
	$(MVN) -DskipTests compile

check: lint test ## The gate: formatting, static analysis and tests

pre-commit: check ## Same gate as `make check`, named for a pre-commit hook

package: ## Build the executable jar into target/
	$(MVN) clean package

jar: package ## Build the jar and run it
	java -jar $(JAR)

clean: ## Remove build output
	$(MVN) clean

deps: ## Download dependencies into the local repository
	$(MVN) dependency:go-offline
