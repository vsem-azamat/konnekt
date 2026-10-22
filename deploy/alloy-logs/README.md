# Log shipper (azamat)

Alloy reads this project's container logs from the Docker socket and pushes
them to Loki on the monitoring server (`loki-push.azamat.io`, Basic Auth, push
only). It lives in `~/deploy/alloy-logs` on the VPS and is started by hand: the
deploy workflow recreates the stack's containers, and a shipper recreated with
them would lose the tail of the deploy that needed watching.

It ships two Compose projects of this host: `supervisor-telegram` (label
`project="konnekt"`) and `gov-cz-bot` (`project="gov-cz"`, the Czech Status
bot); the `project` label matches the one on their metrics. This stack's
compose file states its project name; gov-cz-bot's comes from its directory,
`~/deploy/gov-cz-bot`, so renaming that directory renames the project and
stops its logs. gov-cz-bot writes `level` in upper case (`INFO`, `ERROR`);
Alloy lower-cases it, so `level="error"` finds both projects. Its Caddy access
log is console text, so those lines carry no `level`. That access log holds
every request header, the Mini App's `X-Telegram-Init-Data` login among them;
Alloy replaces it (and the credential headers, which Caddy already hides) with
`<redacted>` before shipping.
Alloy runs as root and a read-only mount of the Docker socket does not limit
the API, so it never sees the socket: a `docker-socket-proxy` on an internal
network does, and answers only GETs for containers and networks. Loki keeps
logs 168 h, shorter than the application's own retention, which is the point.

## Install

```bash
mkdir -p ~/deploy/alloy-logs && cd ~/deploy/alloy-logs
# copy docker-compose.yaml and config.alloy from this directory
install -m 600 /dev/null .env     # then fill it; never print or commit it
#   LOKI_PUSH_USER=...
#   LOKI_PUSH_PASSWORD=...
docker run --rm -v "$PWD/config.alloy:/c.alloy:ro" -e LOKI_PUSH_USER=u -e LOKI_PUSH_PASSWORD=p \
  grafana/alloy:v1.19.2 validate /c.alloy
docker compose up -d
```

## Check

```bash
docker logs alloy-logs --tail 20          # no "401", no "dial" errors
docker run --rm --network alloy-logs_docker-api curlimages/curl -s http://alloy:12345/metrics \
  | grep -E 'loki_write_(sent|dropped)_entries_total'
```

Sent entries rise and dropped stay at zero; in Grafana, `{compose_project="supervisor-telegram"}`
shows lines from `bot`, `webapi`, `catalog-api` and `webui`, and
`{compose_project="gov-cz-bot"}` lines from `backend`, `backup`, `frontend` and `caddy`.

## Roll back

`docker compose down` in the same directory (it removes the proxy too). Loki keeps what it has; nothing in
the application depends on the shipper.
