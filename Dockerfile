# syntax=docker/dockerfile:1.7
# Multi-stage build for optimized production image
FROM python:3.12.13-slim-trixie AS dependencies

COPY --from=ghcr.io/astral-sh/uv:0.11.33 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency files for better caching
COPY pyproject.toml uv.lock README.md ./

# Install dependencies. BuildKit cache mount keeps uv's wheel cache across
# builds even when the layer above invalidates (pyproject.toml / uv.lock
# changed) — avoids redownloading every dep from PyPI on uncached builds.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# The Mini App, with the pnpm its package.json names (packageManager), the
# same one CI's corepack picks: a frozen install refuses a lockfile written by
# another major.
FROM node:24.15.0-alpine3.23 AS web-dependencies

WORKDIR /app/web

COPY web/package.json ./
RUN corepack enable && corepack install
COPY web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

FROM web-dependencies AS web-build

COPY web/ ./
# The commit, which the app reports with each failure (web/src/lib/clientErrors.ts).
# Last, so that a new one rebuilds only the build. It is new on every deploy,
# so the build runs even for a backend-only change, and the entry chunk's hash
# changes with it: a minute of CI and one re-download, for knowing which build
# failed.
ARG WEB_VERSION=unknown
ENV VITE_APP_VERSION=$WEB_VERSION
# Where the app reports its failures (web/src/lib/errorTracking.ts), and the
# Sentry the build uploads the source maps to. The DSN ships in the bundle
# anyway; the token is a build secret, kept out of every layer, and without it
# nothing is uploaded.
ARG VITE_SENTRY_DSN=
ARG SENTRY_ORG=
ARG SENTRY_URL=
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN SENTRY_ORG=$SENTRY_ORG SENTRY_URL=$SENTRY_URL
# Where each lives (PUBLIC_SITE_URL, WEBAPI_PUBLIC_URL): the site names itself
# in canonical links, hreflang and the sitemap, which must be absolute, and the
# app in the way it hands a Telegram launch on (web/site/); the app sends a
# browser to the site (VITE_SITE_URL). Required: unset, a page would name
# localhost, or send somebody nowhere.
ARG SITE_URL
ARG APP_URL
ENV SITE_URL=$SITE_URL APP_URL=$APP_URL VITE_SITE_URL=$SITE_URL
RUN --mount=type=secret,id=SENTRY_AUTH_TOKEN \
    : "${SITE_URL:?pass --build-arg SITE_URL=<the site's https origin>}" && \
    : "${APP_URL:?pass --build-arg APP_URL=<the app's https origin>}" && \
    SENTRY_AUTH_TOKEN="$(cat /run/secrets/SENTRY_AUTH_TOKEN 2>/dev/null || true)" pnpm run build

# Production stage
FROM python:3.12.13-slim-trixie AS production

# Install runtime dependencies only.
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends procps && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root user, logs dir, and set permissions
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --no-create-home appuser && \
    mkdir -p /app/logs && \
    chown appuser:appgroup /app /app/logs

# Copy virtual environment from dependencies stage
COPY --from=dependencies --chown=appuser:appgroup /app/.venv /app/.venv

# Copy application source code
COPY --chown=appuser:appgroup app/ ./app/
COPY --chown=appuser:appgroup alembic/ ./alembic/
COPY --chown=appuser:appgroup alembic.ini ./
COPY --chown=appuser:appgroup --chmod=755 scripts/ ./scripts/

# Make sure we use venv
ENV PATH="/app/.venv/bin:$PATH"

USER appuser

# Health is checked per service in docker-compose.yaml: the bot by its polling
# heartbeat, webapi over HTTP. The process match that stood here matched its
# own shell, so both were always healthy.

ENTRYPOINT ["scripts/entrypoint.sh"]
CMD ["bot"]

FROM caddy:2.11.2-alpine AS webui

COPY docker/Caddyfile /etc/caddy/Caddyfile
# The Mini App, public screens and console alike; docker/Caddyfile routes the
# API paths around it.
COPY --from=web-build /app/web/dist /srv/app

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD caddy validate --config /etc/caddy/Caddyfile >/dev/null || exit 1

# The public site on konnekt.cz (web/site/), in containers of its own: Caddy
# serves the built pages and sends the catalog pages to the Node server the
# same build produced (docker/site/Caddyfile). One image for both, so a
# release is one tag: the `site` service runs Caddy, `site-render` the server.
FROM node:24.15.0-alpine3.23 AS site

COPY --from=caddy:2.11.2-alpine /usr/bin/caddy /usr/bin/caddy
# What Caddy's image adds around it: the media types a file is served with,
# without which the fonts go out with none, and where it keeps its state.
RUN apk add --no-cache mailcap
ENV XDG_CONFIG_HOME=/config XDG_DATA_HOME=/data
COPY docker/site/Caddyfile /etc/caddy/Caddyfile
COPY --from=web-build /app/web/site/dist/client /srv/site
# The server bundles what it imports (site/astro.config.ts); its own copy of
# the built pages is where it looks for them, and the same files as Caddy's.
COPY --from=web-build /app/web/site/dist/server /srv/render/server
RUN ln -s /srv/site /srv/render/client

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD caddy validate --config /etc/caddy/Caddyfile >/dev/null || exit 1
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
