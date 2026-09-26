# syntax=docker/dockerfile:1

# Esta imagem só compila o SPA - não serve nada sozinha. Quem termina TLS e
# roteia por subdomínio é o gateway compartilhado (deploy/gateway/), que lê
# /app/dist deste build. Ver deploy/docker-compose.yml.
FROM node:24.12-alpine AS build
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
COPY contracts /contracts

ARG VITE_API_BASE_URL=/api
ARG VITE_KEYCLOAK_URL=http://localhost:8081
ARG VITE_KEYCLOAK_REALM=synapse
ARG VITE_KEYCLOAK_CLIENT_ID=synapse-frontend
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL
ENV VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM
ENV VITE_KEYCLOAK_CLIENT_ID=$VITE_KEYCLOAK_CLIENT_ID
RUN npm run build
