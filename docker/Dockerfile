# Agent Deck in one container: tmux server, ttyd and the panel, running as an unprivileged user.
# Build from the repository root: docker compose up -d --build
FROM python:3.12-slim-bookworm

ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256_X86_64=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
ARG TTYD_SHA256_AARCH64=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165
ARG DEV_UID=1000

RUN apt-get update \
 && apt-get install -y --no-install-recommends tmux git gh curl ca-certificates procps less openssh-client \
 && rm -rf /var/lib/apt/lists/*
# Debian has no ttyd package: the official static build, pinned by SHA-256.
RUN set -eu; arch=$(uname -m); \
    case "$arch" in x86_64) sum=$TTYD_SHA256_X86_64 ;; aarch64|arm64) arch=aarch64; sum=$TTYD_SHA256_AARCH64 ;; \
      *) echo "unsupported architecture $arch" >&2; exit 1 ;; esac; \
    curl -fsSL -o /usr/local/bin/ttyd "https://github.com/tsl0922/ttyd/releases/download/$TTYD_VERSION/ttyd.$arch"; \
    echo "$sum  /usr/local/bin/ttyd" | sha256sum -c -; chmod 755 /usr/local/bin/ttyd

RUN useradd -m -u "$DEV_UID" -s /bin/bash dev
# Code is root-owned: the in-panel updater cannot rewrite the image, updates come from a new image.
COPY panel/ /opt/cc-panel/
COPY integrations/*.py /opt/cc-panel/integrations/
COPY locales/ /opt/cc-panel/locales/
COPY claude/ /opt/agent-deck/claude/
COPY config/tmux.conf /opt/agent-deck/config/tmux.conf
COPY docker/entrypoint.sh /usr/local/bin/agent-deck-entrypoint
RUN rm -rf /opt/cc-panel/__pycache__ && chmod 755 /usr/local/bin/agent-deck-entrypoint

USER dev
WORKDIR /home/dev
ENV AGENT_DECK_CONTAINER=1 AGENT_DECK_UPDATE_COMMAND="git pull && docker compose up -d --build" PATH=/home/dev/.local/bin:/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8
EXPOSE 8790
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD curl -fsS -o /dev/null http://127.0.0.1:8790/login || exit 1
ENTRYPOINT ["/usr/local/bin/agent-deck-entrypoint"]
