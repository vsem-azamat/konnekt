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
Loki labels, which must stay few.

What is not logged: passwords, tokens, cookies, query strings, and the
audience's ids, except in the moderation lines that name their target (a ban
says whom). A request line names its route template, never the path (a
path carries the ids of the people it is about); the bot's context leaves the
chat id out of private chats, where it is the person's; Caddy's own lines, its
error log included, carry no uri, headers or client address, only the backend
(`handler`) and the id, and the backend's line has the route. Database errors
do not quote their parameters. `tests/unit/test_no_silent_errors.py` holds the
rule that a failure names its class.

## Metrics

| Process | Where Prometheus reads it |
|---|---|
| web API | `https://<site>/api/internal/metrics` |
| catalog API | `https://<site>/api/v1/internal/metrics` |
| bot | `https://<site>/internal/metrics/bot`, routed by the edge to the bot's own port on the host (`127.0.0.1:8789`, free on azamat when this was written) |

All three take `Authorization: Bearer $OBSERVABILITY_METRICS_SECRET`: one
repository secret of 32 characters or more (a shorter one stops the process
from starting), forwarded by the deploy to the bot, the web API and the
catalog API alone. Unset, they answer nothing. The edge route for the bot is
the only thing outside this repository: `/internal/metrics/bot` →
`127.0.0.1:8789/metrics`. The console's own host answers 404 for all of them.

Series, and what never to put in a label, are in `app/core/metrics.py`,
`app/presentation/telegram/metrics.py` and the catalog's `core/metrics.py`;
the rule is in [invariants](../invariants.md#observability).

## The Mini App's own failures

The Mini App reports what fails in it to `POST /api/public/client-errors`
(`web/src/lib/clientErrors.ts`, `app/webapi/routes/client_errors.py`): errors
nothing caught, rejected promises, render errors, calls to our APIs that broke
(no answer, 5xx, or a refused signature), a catalogue that loaded empty, and
an app far shorter than its window. Each is one web API line,
`event="client_error"` at `warning` (so it never reaches the report chat),
with `kind`, `route` (the screen's pattern), `endpoint` and `status` for a
call, `message`, `stack`, `version` (the commit), `platform` and `tg_version`.
Nothing about the person.

Counted in `mini_app_client_errors_total{kind, platform}`; reports the limits
turned away in `mini_app_client_errors_dropped_total{reason}` (`rate_limited`
for one person, `overall_limit` for everybody, `invalid` for an event the
server could not read). `kind` is one of `error`,
`unhandled_rejection`, `render`, `api`, `empty`, `layout`. `kind="api"` with
`status=0` includes requests cut off by the app going to the background or
offline, so it is not worth an alert on its own.

## After a deploy

```bash
curl -fsS -H "Authorization: Bearer $OBSERVABILITY_METRICS_SECRET" https://<site>/api/internal/metrics | head
```

Then the targets in Prometheus are up, and a line from each process appears in
Loki within a minute. Without the secret the web API and the catalog answer
404 (not 401); the bot starts no server, so the edge route to it answers 502.

## Logs from before the last deploy

`docker logs` holds only the current container, which a deploy recreates, and
its last 30 MB, so older lines are only in Loki, which keeps seven days. Loki
answers on the monitoring server's loopback only; an agent on home reaches it
over SSH by address (`poryadok` is not an alias there). The bot's errors of the
last two days, oldest first:

```bash
ssh poryadok@161.97.112.242 'curl -fsS -G http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode "query={compose_project=\"supervisor-telegram\", service=\"bot\"} | json | level=\"error\"" \
  --data-urlencode "start=$(date -u -d "2 days ago" +%s)" \
  --data-urlencode "end=$(date -u +%s)" \
  --data-urlencode limit=200' | jq -r '[.data.result[].values[]] | sort_by(.[0]) | .[][1]'
```

The times are UTC (`date -u -d "2026-10-27 00:00"` for a fixed one), and an
empty answer for a window older than seven days means expired, not quiet.
`limit` keeps the newest lines of the window, so narrow the window rather than
raise it; the `sort_by` matters because after `| json` every field is a label
and nearly every line comes back as a stream of its own. The labels to select
on are `compose_project`, `service` and `level`, and the services are listed by
`curl -fsS http://127.0.0.1:3100/loki/api/v1/label/service/values` there; an
`update_id`, `chat_id` or `request_id` is a field of the JSON line, filtered
after `| json` (`| json | request_id="…"`). With `-f` a query Loki cannot parse
shows only `400 Bad Request`; drop it to see Loki's reason. The lines are the
same as `docker logs` and carry what those carry: keep what you quote from them
to what the question needs.
