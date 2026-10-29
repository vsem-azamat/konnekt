# syntax=docker/dockerfile:1.7

# Build and runtime are separated so the image that ships carries no compilers,
# no uv, and no lockfile — only the virtualenv and the source it needs.

FROM python:3.14.10-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.33 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies resolve from the lockfile alone, in their own layer, so editing
# application code does not reinstall the world.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY src ./src
COPY alembic.ini ./
# The reference data ships with the code that reads it: seeding production is
# not a development-only task, and a seed file that drifts from its loader is
# worse than no seed file.
COPY seeds ./seeds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


# The embedding model, in its own stage so it is one cached layer that changes
# only when the revision below does — every other build reuses it, and every
# deploy but the first pulls nothing extra.
#
# Downloaded at build time and copied in, never fetched when the container
# starts: the image is the unit of deploy and of rollback, and a model pulled at
# startup would make one tag behave differently on different days. See
# docs/architecture.md.
FROM python:3.14.10-slim-bookworm AS model

# A commit, never a branch or a tag: those move, and a model that changes under
# a fixed image tag is the whole failure this stage exists to prevent.
ARG EMBEDDING_REPO=onnx-community/embeddinggemma-300m-ONNX
ARG EMBEDDING_REVISION=5090578d9565bb06545b4552f76e6bc2c93e4a66

RUN pip install --no-cache-dir "huggingface_hub==0.36.0"
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('${EMBEDDING_REPO}', revision='${EMBEDDING_REVISION}', local_dir='/model', allow_patterns=['onnx/model_q4.onnx*', 'tokenizer.json'])"
# Flattened, but kept under the names the repository publishes: the graph names
# its own weight file from inside itself, so a tidier pair breaks the reference
# and the failure shows only when the first query opens the session.
#
# Then checked against the bytes this was built and measured with. The revision
# above already pins the content, so this is the second lock on the same door —
# it is what turns a mirror that changed under us, or a download that ended
# early, into a failed build instead of a search that quietly answers worse.
COPY model.sha256 /model.sha256
RUN mv /model/onnx/model_q4.onnx /model/onnx/model_q4.onnx_data /model/ \
    && rmdir /model/onnx \
    && cd /model \
    && sha256sum --check --strict /model.sha256 \
    && rm /model.sha256


FROM python:3.14.10-slim-bookworm AS runtime

# Non-root from the start. The application writes nothing to disk — Postgres
# holds the state and Telegram holds the files.
RUN groupadd --system --gid 1001 students_cz \
    && useradd --system --uid 1001 --gid students_cz --create-home students_cz

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder --chown=students_cz:students_cz /app/.venv /app/.venv
COPY --from=builder --chown=students_cz:students_cz /app/src /app/src
COPY --from=builder --chown=students_cz:students_cz /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=students_cz:students_cz /app/seeds /app/seeds
COPY --from=model --chown=students_cz:students_cz /model /app/model

USER students_cz
EXPOSE 8000

# One worker, deliberately. The connection pool is per process, so this pin is
# what makes db_pool_size and db_max_overflow the whole budget against Postgres.
# See docs/deploy.md.
CMD ["uvicorn", "students_cz.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
