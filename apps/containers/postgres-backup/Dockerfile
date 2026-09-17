FROM ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie@sha256:ebf3919504d7523a63e8e2fee9b051211de714644b36469275558c624afd50ec
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv curl ca-certificates openssl && rm -rf /var/lib/apt/lists/*
RUN curl --fail --silent --show-error --location https://rolesanywhere.amazonaws.com/releases/1.8.5/X86_64/Linux/Amzn2023/aws_signing_helper -o /usr/local/bin/aws_signing_helper \
 && echo 'beec9ed1c492d93db809890f16713e3556353294b823c2184ad4e891f1b2b54d  /usr/local/bin/aws_signing_helper' | sha256sum -c - \
 && chmod 0755 /usr/local/bin/aws_signing_helper
COPY apps/containers/postgres-backup/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/backup && /opt/backup/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt
COPY apps/platform/postgres /code
ENV PATH="/opt/backup/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
ENTRYPOINT ["python", "/code/backup.py"]
