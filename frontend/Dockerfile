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
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build
