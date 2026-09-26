


build-sandbox-image:
    docker compose -f deploy/docker-compose.yml --env-file deploy/.env --profile build build sandbox
