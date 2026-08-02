# syntax=docker/dockerfile:1.10
FROM node:22.19.0-bookworm-slim@sha256:4a4884e8a44826194dff92ba316264f392056cbe243dcc9fd3551e71cea02b90 AS pi
WORKDIR /opt/pi
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts \
    && npm pack brace-expansion@5.0.9 --pack-destination /tmp \
    && rm -rf node_modules/@earendil-works/pi-coding-agent/node_modules/brace-expansion \
    && mkdir node_modules/@earendil-works/pi-coding-agent/node_modules/brace-expansion \
    && tar -xzf /tmp/brace-expansion-5.0.9.tgz \
        --strip-components=1 \
        -C node_modules/@earendil-works/pi-coding-agent/node_modules/brace-expansion \
    && test "$(node -p \
        'require("./node_modules/@earendil-works/pi-coding-agent/node_modules/brace-expansion/package.json").version')" \
        = "5.0.9" \
    && npm audit --omit=dev \
    && npm cache clean --force

FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
RUN python -m pip install --no-cache-dir uv==0.12.0
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30
ARG BUILD_REVISION=unknown
LABEL org.opencontainers.image.title="Sprinter" \
      org.opencontainers.image.description="Evidence-backed security detection review" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${BUILD_REVISION}"
ENV PATH="/app/.venv/bin:/opt/pi/node_modules/.bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/sprinter \
    PI_TELEMETRY=0 \
    PI_SKIP_VERSION_CHECK=1
RUN groupadd --gid 10001 sprinter \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin sprinter \
    && install -d -o sprinter -g sprinter -m 0700 /var/lib/sprinter /home/sprinter/.pi/agent \
    && rm -rf /usr/local/lib/python3.12/site-packages/pip \
        /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
        /usr/local/bin/pip \
        /usr/local/bin/pip3 \
        /usr/local/bin/pip3.12
COPY --from=build --chown=sprinter:sprinter /app/.venv /app/.venv
COPY --from=pi /opt/pi /opt/pi
COPY --from=pi /usr/local/bin/node /usr/local/bin/node
USER 10001:10001
WORKDIR /app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/livez', timeout=2)"]
CMD ["uvicorn", "sprinter.api:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
