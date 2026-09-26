.DEFAULT_GOAL := help
.PHONY: help install dev build preview check pre-commit type-check lint test format clean

help: ## List available commands
	@grep -hE '^[a-zA-Z_-]+:.*## .*' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	npm install

dev: ## Start the development server
	npm run dev

build: ## Type-check + production build into dist/
	npm run build

preview: ## Serve the production build locally
	npm run preview

check: type-check lint test ## Run type-check, lint and tests — what has to pass before calling it done

pre-commit: check ## Alias for check — run before committing

type-check: ## Check types (vue-tsc)
	npm run type-check

lint: ## Lint with autofix (oxlint + eslint)
	npm run lint

test: ## Run unit tests once
	npm run test:unit -- --run

format: ## Format src/ with prettier
	npm run format

clean: ## Remove build, coverage and local caches
	rm -rf dist coverage node_modules/.tmp .eslintcache
