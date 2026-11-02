# CLAUDE.md

See [AGENTS.md](AGENTS.md) for the working contract and
[docs/invariants.md](docs/invariants.md) for rules the code cannot state itself.

## Quick Reference

```bash
# Run bot locally
uv run -m app.presentation.telegram

# Web API and the Mini App (public screens and the console)
uv run uvicorn app.webapi.main:app --host 127.0.0.1 --port 8787
pnpm --dir web dev

# Tests
uv run -m pytest                                        # all
uv run -m pytest tests/unit tests/handlers tests/middleware -x
uv run -m pytest --cov=app

# Quality
uv run ruff check app tests && uv run ruff format app tests
uv run ty check app tests
pnpm --dir web lint && pnpm --dir web typecheck && pnpm --dir web test

# Migrations
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head

# The catalog API (catalog/, its own project): `make help` lists the rest
make -C catalog setup   # database, dependencies, migrations, reference data
make -C catalog api     # on :8010, where web/'s dev server expects it
```

`docker compose up -d` is the production path and reads its configuration from
the deploying shell, not from a file on the host — deploy through the workflow
rather than running it by hand. See
[docs/deployment/](docs/deployment/).

Structure is not documented here on purpose — it drifts. Read `app/` directly.
