# Server Deployment

This gateway is safe-by-default for server use: it binds to `127.0.0.1` unless configured otherwise, and it refuses to bind a non-loopback host without an API token or explicit auth requirement.

## Runtime Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `DINGTALK_GATEWAY_ENV` | `development` | Label returned by `/health`. |
| `DINGTALK_GATEWAY_HOST` | `127.0.0.1` | Bind address. Use `127.0.0.1` behind Nginx. |
| `DINGTALK_GATEWAY_PORT` | `8787` | HTTP port. |
| `DINGTALK_GATEWAY_REQUIRE_AUTH` | `0` | Set `1` in production. |
| `DINGTALK_GATEWAY_API_TOKEN` | empty | Bearer token for `POST /local/message`. |
| `DINGTALK_GATEWAY_WORKSPACES_CONFIG` | `config/workspaces.json` | Workspace config path. |
| `CODEX_CONFIG` | `/root/.codex/config.toml` | Existing MCP credential source. |

## Systemd Deployment

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

Health check:

```bash
curl http://127.0.0.1:8787/health
```

Authenticated command test:

```bash
TOKEN='replace-with-token-from-env-file'
curl -X POST http://127.0.0.1:8787/local/message \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"cuticlub","sender":"deploy-test","text":"广告状态"}'
```

## Docker Deployment

Docker is useful when the host paths are mounted into the container. The CutiClub workspace and credential files must be available inside the container.

```bash
docker build -t dingtalk-codex-gateway:latest .
docker run --rm -p 127.0.0.1:8787:8787 \
  --env-file deploy/dingtalk-codex-gateway.env.example \
  -e DINGTALK_GATEWAY_API_TOKEN='replace-with-long-token' \
  -v /root/cuticlubads:/root/cuticlubads:rw \
  -v /root/.codex:/root/.codex:ro \
  -v /root/.config/meta-ads-mcp:/root/.config/meta-ads-mcp:ro \
  dingtalk-codex-gateway:latest
```

## Reverse Proxy

Keep the Python service on `127.0.0.1` and put Nginx/Caddy in front for TLS. `deploy/nginx.example.conf` is a minimal Nginx example.

## Security Notes

- `POST /local/message` requires `Authorization: Bearer <token>` whenever `DINGTALK_GATEWAY_API_TOKEN` is set.
- Binding `0.0.0.0` without auth is rejected at startup.
- The gateway still blocks ad writes, store writes, budget changes, and purchase backfills.
- Logs and reports must not contain API tokens or customer PII.
