FROM alpine:3.23 AS alpine-tools

FROM docker.n8n.io/n8nio/n8n:latest

USER root

# Restore the Alpine package manager in the hardened image
COPY --from=alpine-tools /sbin/apk /sbin/apk
COPY --from=alpine-tools /usr/lib/libapk.so* /usr/lib/

# Install the tools required for Shorts generation
RUN apk add --no-cache \
    ffmpeg \
    python3 \
    py3-pip \
    py3-virtualenv \
    bash \
    curl \
    jq \
    coreutils \
    fontconfig \
    ttf-dejavu \
    && python3 -m venv /opt/shorts-venv \
    && /opt/shorts-venv/bin/pip install --no-cache-dir edge-tts \
    && mkdir -p /data /opt/shorts-scripts \
    && chown -R node:node /data /opt/shorts-venv /opt/shorts-scripts

USER node