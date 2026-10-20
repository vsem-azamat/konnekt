# Supervisor Telegram Engineering Rules

The working contract for this repository. `README.md` is the setup guide;
`docs/invariants.md` holds the rules that code cannot state for itself.

## The Loop

1. Write the failing test.
2. Make it pass with the smallest change that fixes the real problem.
3. Refactor once the behaviour is protected.
4. Record an invariant **only** if you discovered a rule a future reader would
   otherwise break. Most changes do not produce one.

Tests are the canon for behaviour. A test that says a tool no longer exists
fails the moment that stops being true; a document saying the same thing rots
in silence. This repository has already paid for that: welcome messages and
captcha were documented as working capabilities for months after the handler
was dropped in the aiogram 2 → 3 migration, and the admin UI kept offering a
captcha toggle that did nothing.

So: do not write prose that restates structure, counts things, or lists
capabilities. Module maps are `ls`. Tool counts are a grep. Both drift, and a
stale map is worse than no map because it is trusted.

## Quality Bar

- Fix root causes, not symptoms.
- Do not ship code you cannot explain.
- Do not hide uncertainty. Mark unknowns and risks explicitly.
- Do not add abstractions until they remove real complexity, isolate an unstable
  boundary, or serve more than one real call site.
- Do not mix unrelated cleanup with feature work unless the cleanup is required
  for the feature.
- Prefer readable domain code over clever generic helpers.
- Do not manually edit generated files when an owning tool exists.

## Architecture

Feature-based and modular: one package per feature under `app/`, named for what
it does. ORM models are the domain models; there is no entity-mapping layer and
no interface layer without a real second implementation.

- Keep feature behaviour inside the owning module.
- Keep route handlers, Telegram handlers, and UI handlers thin. They orchestrate
  services; they do not hold business rules.
- Cross-feature access goes through explicit services or repositories, not
  incidental imports.
- Split a file by responsibility before adding behaviour to one that has become
  hard to review.

## Security

- The admin/public boundary in the web API is a security boundary. Public
  endpoints are intentionally read-only and must not leak admin fields. The
  exceptions write only for the caller Telegram signed, and are listed in
  `docs/invariants.md` under «Mini App».
- Admin mutations require authenticated admin sessions. No bypass paths for
  convenience.
- Make dangerous things unreachable by construction rather than guarded by a
  check — a check can be raced, a missing argument cannot.
- Never log secrets, tokens, session strings, or credentials.
- Telegram- and MCP-specific rules live in `docs/invariants.md`. Read it before
  touching bot identities, the approval gate, or the control plane.

## Database And Deployment

- PostgreSQL 18 is the target.
- Schema changes need an Alembic migration plus tests, verified against
  PostgreSQL when behaviour depends on PostgreSQL features.
- No destructive database commands on shared environments without a stated
  rollback plan.
- Keep deployment reproducible: pin action and image versions, avoid stale tags,
  preserve the `~/deploy/supervisor-telegram/` model unless asked to redesign.

## Verification

Run the narrowest lane that proves the change, then widen when the blast radius
crosses a module boundary. Never claim "done", "fixed", or "clean" without fresh
evidence.

```bash
uv run ruff check app tests
uv run ruff format --check app tests
uv run ty check app tests
uv run pytest                    # everything; the lanes below are subsets
uv run pytest tests/unit tests/handlers tests/middleware tests/utils
uv run pytest tests/integration  # needs PostgreSQL
uv run pytest tests/e2e tests/webapi tests/mcp
pnpm --dir web lint && pnpm --dir web typecheck && pnpm --dir web test
```

`.githooks/` runs the part of these a change can break: the fast ones on commit,
the rest on push. `make hooks` turns them on for every worktree; skip them only
in an emergency, with `--no-verify` or `SKIP_HOOKS=1`.

`ty` currently reports a standing count of pre-existing diagnostics. Compare
against that baseline rather than expecting zero, and do not let your change
raise it.

`catalog/` is a separate Python project with its own lockfile, database and
rules: its product and data rules are `catalog/docs/`, and its checks run from
inside it, where `ty` stands at zero.

```bash
cd catalog && make lint && make test && make contract   # test needs `make db-up`
```

## Working Style

- Inspect the checkout before proposing or editing.
- State assumptions when they affect architecture, data, security, or delivery.
- Read only what you need and summarise findings.
- Do not commit plans, scratchpads, handoff notes, or execution logs as project
  documentation unless explicitly asked for that artifact.
- Stop and name the blocker if access, rollback, or ownership is unclear.

## Git

- Work on a named branch.
- Commit by concern. Stage explicitly and read `git status --short` first.
- Non-destructive commands by default. Do not amend, force-push, reset, or
  revert the user's work unless asked.
