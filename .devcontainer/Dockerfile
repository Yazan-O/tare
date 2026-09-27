FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        gnucobol openjdk-21-jdk-headless \
        python3 python3-pil python-is-python3 git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
