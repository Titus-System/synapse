build-sandbox-image:
	docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile build build sandbox

up:
	docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d

up-build:
	docker compose -f deploy/docker-compose.yml --env-file deploy/.env up --build -d
