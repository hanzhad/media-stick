FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fonts-roboto-unhinted \
        imagemagick \
        kodi \
        kodi-inputstream-adaptive \
        procps \
        python3 \
        python3-requests \
        python3-six \
        scrot \
        unzip \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
EXPOSE 18080 8080 9090

ENTRYPOINT ["/workspace/tools/emulator/run.sh"]
