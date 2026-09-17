FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
COPY --from=ghcr.io/astral-sh/uv:0.12.13@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 /uv /uvx /usr/local/bin/
RUN --mount=type=secret,id=dependency-env --mount=type=secret,id=dependency-apt \
    set -a; if [ ! -f /run/secrets/dependency-env ]; then :; else . /run/secrets/dependency-env; fi; set +a; apt-get update && apt-get install -y --no-install-recommends git ca-certificates zip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --no-compile awscli==1.46.1 \
    && git config --system --add safe.directory /workspace
WORKDIR /workspace
RUN useradd --create-home --uid 1001 builder
USER builder
