# Log shipper (azamat)

Alloy reads this project's container logs from the Docker socket and pushes
them to Loki on the monitoring server (`loki-push.azamat.io`, Basic Auth, push
only). It lives in `~/deploy/alloy-logs` on the VPS and is started by hand: the
deploy workflow recreates the stack's containers, and a shipper recreated with
them would lose the tail of the deploy that needed watching.

It ships the `supervisor-telegram` Compose project only. The socket is mounted
read-only, which still shows every container on the host; the filter in
`config.alloy` is what keeps the other stacks' logs here.

## Install

```bash
mkdir -p ~/deploy/alloy-logs && cd ~/deploy/alloy-logs
# copy docker-compose.yaml and config.alloy from this directory
install -m 600 /dev/null .env     # then fill it; never print or commit it
#   LOKI_PUSH_USER=...
#   LOKI_PUSH_PASSWORD=...
#   DOCKER_GID=$(stat -c %g /var/run/docker.sock)
docker run --rm -v "$PWD/config.alloy:/c.alloy:ro" -e LOKI_PUSH_USER=u -e LOKI_PUSH_PASSWORD=p \
  grafana/alloy:v1.19.2 validate /c.alloy
docker compose up -d
```

## Check

```bash
docker logs alloy-logs --tail 20          # no "401", no "dial" errors
curl -s 127.0.0.1:12346/metrics | grep -E 'loki_write_(sent|dropped)_entries_total'
```

Sent entries rise and dropped stay at zero; in Grafana, `{compose_project="supervisor-telegram"}`
shows lines from `bot`, `webapi`, `catalog-api` and `webui`.

## Roll back

`docker compose down` in the same directory. Loki keeps what it has; nothing in
the application depends on the shipper.
