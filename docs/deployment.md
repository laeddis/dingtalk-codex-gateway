# Server Deployment

This gateway is safe-by-default for server use: it requires bearer-token auth for Docker deployments, keeps write actions blocked, and can run behind Caddy for automatic public HTTPS.

## Runtime Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `DINGTALK_GATEWAY_ENV` | `development` | Label returned by `/health`. |
| `DINGTALK_GATEWAY_HOST` | `127.0.0.1` | Bind address inside the runtime. Docker uses `0.0.0.0` inside the container. |
| `DINGTALK_GATEWAY_PORT` | `8787` | HTTP port. |
| `DINGTALK_GATEWAY_REQUIRE_AUTH` | `0` | Set `1` in production. Docker sets this automatically. |
| `DINGTALK_GATEWAY_API_TOKEN` | empty | Bearer token for `POST /local/message`. |
| `DINGTALK_GATEWAY_DEFAULT_WORKSPACE` | `default` | Workspace used when a request omits `workspace`. Compose sets `default`. |
| `DINGTALK_GATEWAY_WORKSPACES_CONFIG` | `config/workspaces.json` | Workspace config path. |
| `CODEX_CONFIG` | `/root/.codex/config.toml` | Existing MCP credential source. |

## Public HTTPS Docker Compose Deployment (Recommended)

Use this for a public server. Caddy listens on ports `80` and `443`, obtains/renews Let's Encrypt certificates automatically, and reverse-proxies to the gateway container.

Prerequisites:

- A domain or subdomain pointing to the server's public IP.
- Ports `80/tcp`, `443/tcp`, and `443/udp` open on the firewall/security group.
- Docker Engine with the Compose plugin installed.
- A long random `DINGTALK_GATEWAY_API_TOKEN`.

Deploy:

```bash
cd /root/dingtalk-codex-gateway
cp deploy/docker-compose.env.example deploy/docker-compose.env
chmod 600 deploy/docker-compose.env
editor deploy/docker-compose.env

# Set at least:
# DINGTALK_GATEWAY_API_TOKEN=<long-random-token>
# DINGTALK_GATEWAY_DOMAIN=<your-domain>
# CADDY_ACME_EMAIL=<your-email>
# WORKSPACE_HOST_PATH=<absolute-path-to-your-workspace>

docker compose --env-file deploy/docker-compose.env -f compose.yaml -f compose.https.yaml build
docker compose --env-file deploy/docker-compose.env -f compose.yaml -f compose.https.yaml up -d
docker compose --env-file deploy/docker-compose.env -f compose.yaml -f compose.https.yaml ps
```

Health check:

```bash
curl https://$DINGTALK_GATEWAY_DOMAIN/health
```

Authenticated command test:

```bash
set -a
. deploy/docker-compose.env
set +a

curl -X POST https://$DINGTALK_GATEWAY_DOMAIN/local/message \
  -H "Authorization: Bearer $DINGTALK_GATEWAY_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"default","sender":"compose-test","text":"广告状态"}'
```

Logs and lifecycle:

```bash
docker compose --env-file deploy/docker-compose.env -f compose.yaml -f compose.https.yaml logs -f gateway
docker compose --env-file deploy/docker-compose.env -f compose.yaml -f compose.https.yaml logs -f caddy
docker compose --env-file deploy/docker-compose.env -f compose.yaml -f compose.https.yaml restart gateway
docker compose --env-file deploy/docker-compose.env -f compose.yaml -f compose.https.yaml down
```

Compose mounts these host paths by default:

| Host path | Container path | Purpose |
| --- | --- | --- |
| `./config` | `/app/config` | Workspace config. |
| `./logs` | `/app/logs` | Audit JSONL logs. |
| `./reports` | `/app/reports` | Generated Markdown reports. |
| `${WORKSPACE_HOST_PATH}` | `/workspace` | External business workspace. |
| `${CODEX_CONFIG_DIR}` | `/root/.codex` | Existing MCP credentials. |
| `${META_ADS_MCP_CONFIG_DIR}` | `/root/.config/meta-ads-mcp` | Meta token fallback. |

The Compose deployment uses `config/workspaces.compose.json`, where workspace `default` points to `/workspace`. Set `WORKSPACE_HOST_PATH` to the host directory you want mounted there.

## Localhost-Only Docker Compose

Use this if HTTPS is handled by another reverse proxy or load balancer.

```bash
cd /root/dingtalk-codex-gateway
cp deploy/docker-compose.env.example deploy/docker-compose.env
chmod 600 deploy/docker-compose.env
editor deploy/docker-compose.env

docker compose --env-file deploy/docker-compose.env build
docker compose --env-file deploy/docker-compose.env up -d
```

The base Compose file publishes only `127.0.0.1:${DINGTALK_GATEWAY_PUBLISHED_PORT:-8787}`.

## Single Docker Container

```bash
docker build -t dingtalk-codex-gateway:latest .
docker run --rm -p 127.0.0.1:8787:8787 \
  -e DINGTALK_GATEWAY_ENV=production \
  -e DINGTALK_GATEWAY_HOST=0.0.0.0 \
  -e DINGTALK_GATEWAY_PORT=8787 \
  -e DINGTALK_GATEWAY_REQUIRE_AUTH=1 \
  -e DINGTALK_GATEWAY_API_TOKEN='replace-with-long-token' \
  -e DINGTALK_GATEWAY_DEFAULT_WORKSPACE=default \
  -e DINGTALK_GATEWAY_WORKSPACES_CONFIG=/app/config/workspaces.compose.json \
  -e CODEX_CONFIG=/root/.codex/config.toml \
  -v ./config:/app/config:ro \
  -v ./logs:/app/logs \
  -v ./reports:/app/reports \
  -v /absolute/path/to/workspace:/workspace:rw \
  -v /root/.codex:/root/.codex:ro \
  -v /root/.config/meta-ads-mcp:/root/.config/meta-ads-mcp:ro \
  dingtalk-codex-gateway:latest
```

## Systemd Deployment

Systemd remains available for non-container deployments.

```bash
cd /root/dingtalk-codex-gateway
python3 -m unittest discover -s tests -v

sudo cp deploy/dingtalk-codex-gateway.env.example /etc/dingtalk-codex-gateway.env
sudo chmod 600 /etc/dingtalk-codex-gateway.env
sudo editor /etc/dingtalk-codex-gateway.env

sudo cp deploy/dingtalk-codex-gateway.service /etc/systemd/system/dingtalk-codex-gateway.service
sudo systemctl daemon-reload
sudo systemctl enable --now dingtalk-codex-gateway
sudo systemctl status dingtalk-codex-gateway
```

## Security Notes

- `POST /local/message` requires `Authorization: Bearer <token>` whenever `DINGTALK_GATEWAY_API_TOKEN` is set.
- Binding `0.0.0.0` without auth is rejected at startup.
- The gateway blocks ad writes, store writes, budget changes, and purchase backfills.
- Logs and reports must not contain API tokens or customer PII.
- Keep `deploy/docker-compose.env` out of git.
