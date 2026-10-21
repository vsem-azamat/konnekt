# Observability

How the three processes (bot, web API, catalog API) and the web UI's Caddy
report to the monitoring stack on the shared server (Prometheus, Loki,
Grafana, Alloy). The stack's own configuration lives with that server's
repository and wiki; this page is what this repository must keep true.

## Logs

Every process writes JSON lines to stdout, which Docker keeps and an agent
ships to Loki. A line carries `level`, `logger`, `event` and, while it is
handled, the context bound for it: `request_id` in the web API and the catalog
API, `update_id`, `update_type`, `chat_id` and `handler` in the bot. Caddy
generates the request id and passes it as `X-Request-Id`, so one id finds the
proxy's line and the backend's.

An error is found by `level="error"`, and its traceback is in the same line
(`exception`). Search on an id by parsing the JSON in the query; ids are not
Loki labels, which must stay few. Passwords, tokens, query strings, cookies and
the audience's ids are not logged; `tests/unit/test_no_silent_errors.py`
holds the rule that a failure names its class.

## Metrics

| Process | Where Prometheus reads it |
|---|---|
| web API | `https://<site>/api/internal/metrics` |
| catalog API | `https://<site>/api/v1/internal/metrics` |
| bot | `https://<site>/internal/metrics/bot`, routed by the edge to the bot's own port on the host |

All three take `Authorization: Bearer $OBSERVABILITY_METRICS_SECRET`: one
repository secret, forwarded by the deploy to the bot, the web API and the
catalog API alone. Unset, they answer nothing. The edge route for the bot is
the only thing outside this repository: `/internal/metrics/bot` →
`127.0.0.1:8789/metrics`. The console's own host answers 404 for all of them.

Series, and what never to put in a label, are in `app/core/metrics.py`,
`app/presentation/telegram/metrics.py` and the catalog's `core/metrics.py`;
the rule is in [invariants](../invariants.md#observability).

## After a deploy

```bash
curl -fsS -H "Authorization: Bearer $OBSERVABILITY_METRICS_SECRET" https://<site>/api/internal/metrics | head
```

Then the targets in Prometheus are up, and a line from each process appears in
Loki within a minute. Without the secret all three answer 404, not 401.
