# Log shipper (azamat)

Alloy reads this project's container logs from the Docker socket and pushes
them to Loki on the monitoring server (`loki-push.azamat.io`, Basic Auth, push
only). It lives in `~/deploy/alloy-logs` on the VPS and is started by hand: the
deploy workflow recreates the stack's containers, and a shipper recreated with
them would lose the tail of the deploy that needed watching.

It ships the `supervisor-telegram` Compose project only (the stack's compose
file states that name itself, so the filter does not depend on a directory).
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
shows lines from `bot`, `webapi`, `catalog-api` and `webui`.

## Roll back

`docker compose down` in the same directory (it removes the proxy too). Loki keeps what it has; nothing in
the application depends on the shipper.
