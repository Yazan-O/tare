# Tare toolchain: GnuCOBOL (Berkeley DB indexed files), JDK 21, Python 3 with Pillow, git.
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

# gnucobol -> gnucobol3 3.1.2, whose runtime libcob4t64 links libdb5.3 (indexed files);
# python3-pil is Pillow 10.2; python-is-python3 makes `python` work.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        gnucobol openjdk-21-jdk-headless \
        python3 python3-pil python-is-python3 git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
