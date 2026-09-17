# Existing ARC runner version and verified base digest.
FROM ghcr.io/actions/actions-runner:2.337.0@sha256:e5496277be5d09bc968b3d64911b74e219ac4a3f2edce956a3ecf9271bea1ef4
USER root
# Union of recurring prerequisites declared by talos-runner-setup callers.
# APT retains repository signature verification. The published image is pinned by digest.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip jq curl git unzip zip gh dnsutils \
    openssh-client rsync shellcheck docker-compose-v2 \
    && dpkg-query -W > /opt/ci-packages.tsv \
    && rm -rf /var/lib/apt/lists/*
COPY cache_download.py /tmp/cache_download.py
RUN python3 /tmp/cache_download.py \
      https://awscli.amazonaws.com/awscli-exe-linux-x86_64-2.36.45.zip \
      0f02381483b0a5ca127a4cb379e656a73007b346561a5e41d3249d3bc1861226 \
      /tmp/aws.zip \
    && unzip -q /tmp/aws.zip -d /tmp/aws-install \
    && /tmp/aws-install/aws/install \
    && rm -rf /tmp/aws-install /tmp/aws.zip /tmp/cache_download.py \
    && aws --version && docker compose version
USER runner
