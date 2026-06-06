# DingTalk Codex Gateway

本项目是独立的本地 DingTalk → Codex/运营脚本网关，不和 `/root/cuticlubads` 混在一起。

## 当前状态

MVP 已实现本地测试接口：

- `GET /health`
- `POST /local/message`
- 支持 `订单日报 今天/昨天 store=shopline|shoplazza|all`
- 高风险命令拦截：广告启停/预算/创建、店铺产品/折扣/主题/导航、订单或 purchase 回传
- 审计日志：`logs/commands.jsonl`
- 本地报告：`reports/*.md`

其他命令（广告日报、检查漏单、广告状态）先安全返回 not implemented。

## 运行

```bash
cd /root/dingtalk-codex-gateway
python3 -m src.server
```

服务只绑定 `127.0.0.1:8787`。

## 本地测试

```bash
curl http://127.0.0.1:8787/health

curl -X POST http://127.0.0.1:8787/local/message \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"cuticlub","sender":"local-user","text":"订单日报 今天 store=all"}'

curl -X POST http://127.0.0.1:8787/local/message \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"cuticlub","sender":"local-user","text":"暂停广告"}'
```

单元测试：

```bash
python3 -m unittest discover -s tests -v
```

## 凭据来源

网关读取 `/root/.codex/config.toml` 里的 MCP 环境变量，只使用这些 key，不输出 token：

- `mcp_servers.shopline.env.SHOPLINE_*`
- `mcp_servers.shoplazza.env.SHOPLAZZA_*`

## 安全边界

DingTalk MVP 默认只允许读数据和写本地报告。真实外部写操作必须回到 Codex CLI 主会话手动执行并明确确认。
