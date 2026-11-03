FROM mcr.microsoft.com/devcontainers/python:3-3.12-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
