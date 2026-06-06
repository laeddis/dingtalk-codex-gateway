# DingTalk Codex Gateway

本项目是独立的本地 DingTalk → Codex/运营脚本网关，不和 `/root/cuticlubads` 混在一起。

## 当前状态

MVP 已实现可部署的本地 HTTP 接口：

- `GET /health`
- `POST /local/message`
- 支持 `订单日报 今天/昨天 store=shopline|shoplazza|all`
- 支持 `广告日报 今天/昨天`：只读查询本地已知 campaign 的 Meta campaign-level 数据
- 支持 `检查漏单 今天/昨天`：调用 CutiClub 现有 Shopline ↔ Meta Purchase 对账脚本
- 支持 `广告状态`：优先只读查询 Meta campaign/ad set/ad 实时状态，token 不可用时回退到 CutiClub 本地 `ad_tests` 快照
- 高风险命令拦截：广告启停/预算/创建、店铺产品/折扣/主题/导航、订单或 purchase 回传
- 审计日志：`logs/commands.jsonl`
- 本地报告：`reports/*.md`
- 支持 env/CLI 配置、Bearer token 保护、systemd 和 Docker 部署

未识别命令先安全返回 not implemented。

## 运行

```bash
cd /root/dingtalk-codex-gateway
python3 -m src.server
```

默认只绑定 `127.0.0.1:8787`。生产环境建议继续绑定 localhost，在 Nginx/Caddy 后面提供 HTTPS。

常用环境变量：

```bash
export DINGTALK_GATEWAY_ENV=production
export DINGTALK_GATEWAY_HOST=127.0.0.1
export DINGTALK_GATEWAY_PORT=8787
export DINGTALK_GATEWAY_REQUIRE_AUTH=1
export DINGTALK_GATEWAY_API_TOKEN='replace-with-a-long-random-token'
python3 -m src.server
```

也可以安装为命令：

```bash
python3 -m pip install .
dingtalk-codex-gateway --env-file /etc/dingtalk-codex-gateway.env
```

完整服务器部署见 `docs/deployment.md`。

## 本地测试

```bash
curl http://127.0.0.1:8787/health

curl -X POST http://127.0.0.1:8787/local/message \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"cuticlub","sender":"local-user","text":"订单日报 今天 store=all"}'

curl -X POST http://127.0.0.1:8787/local/message \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"cuticlub","sender":"local-user","text":"广告日报 昨天"}'

curl -X POST http://127.0.0.1:8787/local/message \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"cuticlub","sender":"local-user","text":"暂停广告"}'

curl -X POST http://127.0.0.1:8787/local/message \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"cuticlub","sender":"local-user","text":"检查漏单 昨天"}'

curl -X POST http://127.0.0.1:8787/local/message \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"cuticlub","sender":"local-user","text":"广告状态"}'
```

如果设置了 `DINGTALK_GATEWAY_API_TOKEN`，`POST /local/message` 需要：

```bash
-H "Authorization: Bearer $DINGTALK_GATEWAY_API_TOKEN"
```

单元测试：

```bash
python3 -m unittest discover -s tests -v
```

## 凭据来源

网关读取本地已有凭据，只使用这些 key，不输出 token：

- `mcp_servers.shopline.env.SHOPLINE_*`
- `mcp_servers.shoplazza.env.SHOPLAZZA_*`
- Meta 只读查询优先读取环境变量 `META_ACCESS_TOKEN` / `FACEBOOK_ACCESS_TOKEN` / `FB_ACCESS_TOKEN`，并兼容 `/root/.config/meta-ads-mcp/env`。

## 安全边界

DingTalk MVP 默认只允许读数据和写本地报告。真实外部写操作必须回到 Codex CLI 主会话手动执行并明确确认。
